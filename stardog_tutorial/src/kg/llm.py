"""Question answering over the knowledge graph with a local LLM (Chapter 16).

Three strategies:
  text_to_sparql()   the LLM writes SPARQL from a schema summary; validated, run, retried on errors
  GraphRAG           embeddings find the entities, the graph supplies the facts, the LLM answers from them
  ask_with_tools()   the LLM picks one of a few reviewed queries (tools) and fills in the parameters

Needs Ollama running locally (see kg.extraction). LLM calls are cached so reruns are reproducible.
"""
import hashlib
import json
import re
from pathlib import Path

import requests
import stardog
from rdflib.plugins.sparql import prepareQuery

from kg import extraction, sparql

MODEL = extraction.EXTRACT_MODEL


def chat(messages: list[dict], tools: list | None = None, json_mode: bool = False, cache: Path | None = None) -> dict:
  """One Ollama chat turn (temperature 0, fixed seed). Returns the assistant message."""
  body = {'model': MODEL, 'messages': messages, 'stream': False, 'options': {'temperature': 0, 'seed': 42}}
  if tools:
    body['tools'] = tools
  if json_mode:
    body['format'] = 'json'
  key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:20]
  store = json.loads(cache.read_text(encoding='utf-8')) if cache and cache.exists() else {}
  if key not in store:
    r = requests.post(f'{extraction.OLLAMA_URL}/api/chat', json=body, timeout=600)
    r.raise_for_status()
    store[key] = r.json()['message']
    if cache:
      cache.write_text(json.dumps(store, indent=1), encoding='utf-8')
  return store[key]


# ---- 1. schema summary ---------------------------------------------------------------------------

def schema_summary(conn: stardog.Connection, model_graph: str, data_graph: str, prefixes: dict[str, str],
                   samples: dict[str, str] | None = None) -> str:
  """A compact, LLM-friendly description of the model.

  samples: {label: graph pattern binding ?v}, e.g. {'allergen names': '?a a rec:Allergen ; rec:name ?v'},
  lists real values so the LLM spells literals exactly as they are stored.
  """
  def short(iri):
    for p, ns in prefixes.items():
      if iri.startswith(ns):
        return f'{p}:{iri[len(ns):]}'
    return f'<{iri}>'

  classes = sparql.run_query(conn, '''PREFIX owl: <http://www.w3.org/2002/07/owl#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?c ?comment { ?c a owl:Class FILTER(isIRI(?c)) OPTIONAL { ?c rdfs:comment ?comment } } ORDER BY ?c''', graphs=model_graph)
  props = sparql.run_query(conn, '''PREFIX owl: <http://www.w3.org/2002/07/owl#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?p ?kind ?domain ?range ?comment {
      VALUES ?kind { owl:ObjectProperty owl:DatatypeProperty } ?p a ?kind
      OPTIONAL { ?p rdfs:domain ?domain } OPTIONAL { ?p rdfs:range ?range } OPTIONAL { ?p rdfs:comment ?comment } }
    ORDER BY ?p''', graphs=model_graph)

  lines = ['PREFIXES:'] + [f'  PREFIX {p}: <{ns}>' for p, ns in prefixes.items()] + ['', 'CLASSES:']
  for r in classes.itertuples():
    lines.append(f'  {short(r.c)}' + (f'  -- {r.comment}' if isinstance(r.comment, str) else ''))
  lines += ['', 'PROPERTIES (subject class -> value):']
  for r in props.drop_duplicates('p').itertuples():
    dom = short(r.domain) if isinstance(r.domain, str) else 'any'
    rng = short(r.range) if isinstance(r.range, str) else 'any'
    note = f'  -- {r.comment}' if isinstance(r.comment, str) else ''
    lines.append(f'  {short(r.p)}: {dom} -> {rng}{note}')
  if samples:
    lines += ['', 'EXAMPLE VALUES (spell literals exactly like this):']
    declared = ''.join(f'PREFIX {p}: <{ns}> ' for p, ns in prefixes.items())
    for label, pattern in samples.items():
      values = sparql.run_query(conn, declared + f'SELECT DISTINCT ?v {{ {pattern} FILTER(isLiteral(?v)) }} ORDER BY ?v LIMIT 60',
                                graphs=data_graph).v.astype(str).tolist()
      lines.append(f'  {label}: ' + ', '.join(f'"{v}"' for v in values))
  return '\n'.join(lines)


def ensure_prefixes(query: str, prefixes: dict[str, str]) -> str:
  """Add PREFIX declarations the query uses but forgot: a deterministic repair instead of another LLM round."""
  declared = set(re.findall(r'PREFIX\s+([A-Za-z][\w-]*)\s*:', query, re.I))
  body = re.sub(r'<[^>]*>|"[^"]*"', '', query)                      # ignore IRIs and strings
  used = set(re.findall(r'\b([a-z][\w-]*):[A-Za-z_]', body))
  missing = [p for p in prefixes if p in used and p not in declared]
  return ''.join(f'PREFIX {p}: <{prefixes[p]}>\n' for p in missing) + query


# ---- 2. text-to-SPARQL ---------------------------------------------------------------------------

SPARQL_SYSTEM = '''You translate questions into SPARQL for a Stardog knowledge graph.
Rules:
- Use ONLY the prefixes, classes and properties listed in the schema. Never invent properties.
- Write one SELECT query. Declare every prefix you use. No FROM clause. No INSERT, DELETE or other updates.
- Recipe names have language tags: filter with FILTER(lang(?name) = "en") and return names, not IRIs.
- Compare literal values exactly as in EXAMPLE VALUES (same spelling and case).
- Return only the query, in a ```sparql code block.

SCHEMA:
'''

FORBIDDEN = re.compile(r'\b(INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|ADD|MOVE|COPY)\b', re.I)


def _extract_query(text: str) -> str:
  block = re.search(r'```(?:sparql)?\s*(.*?)```', text, re.S)
  return (block.group(1) if block else text).strip()


def validate_sparql(query: str, schema: str) -> list[str]:
  """Problems found before running: syntax, updates, unknown vocabulary. Empty list = OK."""
  problems = []
  if FORBIDDEN.search(re.sub(r'"[^"]*"', '', query)):
    problems.append('Only read-only SELECT queries are allowed.')
  try:
    prepareQuery(query)
  except Exception as e:
    problems.append(f'Syntax error: {str(e)[:200]}')
  known = set(re.findall(r'\b([a-z]+:[A-Za-z0-9_]+)', schema))
  used = {t for t in re.findall(r'\b(rec:[A-Za-z0-9_]+)', query)}
  unknown = sorted(used - known)
  if unknown:
    problems.append(f'Unknown terms (not in the schema): {", ".join(unknown)}')
  return problems


def text_to_sparql(conn, question: str, schema: str, graphs, *, schema_name: str, examples: list[tuple[str, str]] = (),
                   prefixes: dict[str, str] | None = None, max_attempts: int = 3, cache: Path | None = None) -> dict:
  """Generate, validate, run and (on problems) retry. Returns the final query, rows, and every attempt.

  examples: (question, SPARQL) pairs shown to the model first (few-shot).
  prefixes: if given, missing PREFIX declarations are added automatically before validation.
  """
  messages = [{'role': 'system', 'content': SPARQL_SYSTEM + schema}]
  for q, a in examples:
    messages += [{'role': 'user', 'content': q}, {'role': 'assistant', 'content': f'```sparql\n{a}\n```'}]
  messages.append({'role': 'user', 'content': question})
  attempts = []
  for _ in range(max_attempts):
    reply = chat(messages, cache=cache)['content']
    query = _extract_query(reply)
    if prefixes:
      query = ensure_prefixes(query, prefixes)
    problems = validate_sparql(query, schema)
    rows = None
    if not problems:
      try:
        rows = sparql.run_query(conn, query, graphs=graphs, reasoning=True, schema=schema_name, limit=100)
        if rows.empty:
          problems.append('The query ran but returned no rows. Check literal values, language tags and property directions.')
      except stardog.exceptions.StardogException as e:
        problems.append(f'Stardog error: {str(e)[:300]}')
    attempts.append({'query': query, 'problems': problems, 'rows': None if rows is None else len(rows)})
    if not problems:
      return {'query': query, 'rows': rows, 'attempts': attempts}
    messages += [{'role': 'assistant', 'content': reply},
                 {'role': 'user', 'content': 'That query has problems:\n- ' + '\n- '.join(problems) + '\nPlease fix it.'}]
  return {'query': query, 'rows': rows, 'attempts': attempts}


def answer_from_rows(question: str, rows, cache: Path | None = None) -> str:
  """Phrase an answer using only the query result."""
  table = rows.to_csv(index=False) if rows is not None and len(rows) else '(no results)'
  return chat([{'role': 'system', 'content': 'Answer the question using ONLY the query results given. '
                'If they are empty, say you could not find an answer. Be brief; list names exactly as written.'},
               {'role': 'user', 'content': f'Question: {question}\n\nQuery results (CSV):\n{table}'}], cache=cache)['content']


# ---- 3. GraphRAG ---------------------------------------------------------------------------------

class GraphRAG:
  """Vector search over entity names -> neighbourhood facts from the graph -> grounded answer."""

  def __init__(self, conn, graphs, schema_name: str | None, entity_query: str, fact_query: str, cache: Path | None = None):
    """entity_query returns ?entity ?label; fact_query returns ?s ?p ?o facts for a bound ?entity (as text).

    schema_name: the reasoning model for the fact query, or None to query without reasoning
    (e.g. when the inferences are materialized, Chapter 18).
    """
    self.conn, self.graphs, self.schema_name, self.fact_query, self.cache = conn, graphs, schema_name, fact_query, cache
    ents = sparql.run_query(conn, entity_query, graphs=graphs)
    self.entities = list(zip(ents.entity, ents.label))
    self.vectors = extraction.embed([label for _, label in self.entities], kind='document')

  def retrieve(self, question: str, k: int = 6) -> list[tuple[str, str, float]]:
    q = extraction.embed([question])[0]
    scored = sorted(((extraction.cosine(q, v), e, label) for (e, label), v in zip(self.entities, self.vectors)), reverse=True)
    return [(e, label, round(s, 3)) for s, e, label in scored[:k]]

  def facts(self, entities: list[str]) -> list[str]:
    from rdflib import URIRef
    lines = []
    for e in entities:
      rows = sparql.run_query(self.conn, self.fact_query, graphs=self.graphs, reasoning=self.schema_name is not None,
                              schema=self.schema_name, entity=URIRef(e))
      lines += [f'{r.s} | {r.p} | {r.o}' for r in rows.itertuples()]
    return sorted(set(lines))

  def ask(self, question: str, k: int = 6) -> dict:
    found = self.retrieve(question, k)
    facts = self.facts([e for e, _, _ in found])
    answer = chat([{'role': 'system', 'content': 'Answer the question using ONLY the facts given (subject | property | value). '
                    'If the facts are not enough, say so. Be brief; list names exactly as written.'},
                   {'role': 'user', 'content': f'Question: {question}\n\nFacts:\n' + '\n'.join(facts)}], cache=self.cache)['content']
    return {'answer': answer, 'retrieved': found, 'facts': facts}


# ---- 4. tools ------------------------------------------------------------------------------------

def ask_with_tools(conn, question: str, tools: dict, graphs, *, schema_name: str, cache: Path | None = None) -> dict:
  """tools = {name: {'description': ..., 'parameters': {param: json_type}, 'query': 'recipes/x', 'reasoning': bool}}."""
  specs = [{'type': 'function', 'function': {
            'name': name, 'description': t['description'],
            'parameters': {'type': 'object', 'properties': {p: {'type': ty} for p, ty in t['parameters'].items()},
                           'required': list(t['parameters'])}}} for name, t in tools.items()]
  messages = [{'role': 'system', 'content': 'You answer questions about a recipe collection. Always call exactly one tool '
               'to get the data, then answer briefly from its result, listing names exactly as written.'},
              {'role': 'user', 'content': question}]
  reply = chat(messages, tools=specs, cache=cache)
  calls = reply.get('tool_calls') or []
  if not calls:
    return {'answer': reply.get('content', ''), 'tool': None, 'arguments': None, 'rows': None}
  call = calls[0]['function']
  name, args = call['name'], call.get('arguments') or {}
  if name not in tools:
    return {'answer': f'(the model asked for an unknown tool {name!r})', 'tool': name, 'arguments': args, 'rows': None}
  spec = tools[name]
  args = {p: args[p] for p in spec['parameters'] if p in args}            # drop anything unexpected
  rows = sparql.run_query(conn, spec['query'], graphs=graphs, reasoning=spec.get('reasoning', False),
                          schema=schema_name if spec.get('reasoning') else None, **args)
  messages += [reply, {'role': 'tool', 'content': rows.to_csv(index=False) or '(no rows)'}]
  final = chat(messages, cache=cache)
  return {'answer': final.get('content', ''), 'tool': name, 'arguments': args, 'rows': rows}
