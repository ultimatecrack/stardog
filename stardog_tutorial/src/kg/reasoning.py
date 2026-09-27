"""Explanations, consistency checks and query plans for reasoning with a named model.

pystardog's explain_inference / is_consistent / explain_inconsistency don't accept a schema
name, so they only use the default schema. These helpers call the same HTTP endpoints with
`schema=<model>` added.
"""
from rdflib import BNode, Graph, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF

import stardog

from kg import recipes
from kg.sparql import term

_NAMESPACES = {**recipes.PREFIXES, 'owl': 'http://www.w3.org/2002/07/owl#',
               'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
               'xsd': 'http://www.w3.org/2001/XMLSchema#', 'rule': 'tag:stardog:api:rule:'}


def _params(schema, graph=None):
  params = {'schema': schema}
  if graph:
    params['graph-uri'] = graph
  return params


def explain(conn: stardog.Connection, subject, predicate, obj, schema: str) -> list:
  """Proof tree(s) for one (possibly inferred) triple: [{'status', 'expression', 'children'}]."""
  triple = f'{term(subject)} {term(predicate)} {term(obj)} .'
  r = conn.client.post('/reasoning/explain', params=_params(schema), data=triple.encode(),
                       headers={'Content-Type': 'text/turtle'})
  return r.json()['proofs']


def is_consistent(conn: stardog.Connection, schema: str, graph: str | None = None) -> bool:
  r = conn.client.get('/reasoning/consistency', params=_params(schema, graph))
  return r.text.strip().lower() == 'true'


def explain_inconsistency(conn: stardog.Connection, schema: str, graph: str | None = None) -> list:
  r = conn.client.get('/reasoning/explain/inconsistency', params=_params(schema, graph))
  return r.json()['proofs']


def query_plan(conn: stardog.Connection, query: str, graphs=None, *, reasoning=False, schema=None) -> str:
  """The query plan Stardog would use, optionally with reasoning (shows the rewriting)."""
  data = {'query': query}
  if graphs:
    data['default-graph-uri'] = graphs
  if reasoning:
    data.update({'reasoning': 'true', 'schema': schema})
  return conn.client.post('/explain', data=data, headers={'Accept': 'text/plain'}).text


# ---- readable proofs -------------------------------------------------------

def _short(node, g: Graph) -> str:
  if isinstance(node, URIRef):
    for prefix, ns in _NAMESPACES.items():
      if str(node).startswith(str(ns)):
        return f'{prefix}:{str(node)[len(str(ns)):]}'
    return f'<{node}>'
  if isinstance(node, BNode):
    if (node, RDF.first, None) in g:                     # an RDF list, e.g. a property chain
      return '( ' + ' '.join(_short(x, g) for x in Collection(g, node)) + ' )'
    return '[…]'
  if node.datatype:
    return f'"{node}"^^{_short(node.datatype, g)}'
  return node.n3()


def _statements(expression: str) -> list[str]:
  g = Graph().parse(data=expression, format='turtle')
  if any('swrl#' in str(t) for t in g.predicates()) or any('swrl#' in str(o) for o in g.objects()):
    return ['(a Stardog rule, see ontology/recipes_rules.ttl)']
  list_nodes = {s for s in g.subjects(RDF.first, None)}
  owl = 'http://www.w3.org/2002/07/owl#'
  for s in g.subjects(RDF.type, URIRef(owl + 'AllDisjointClasses')):
    return [f"owl:AllDisjointClasses {_short(g.value(s, URIRef(owl + 'members')), g)}"]
  lines = []
  for s, p, o in g:
    if s in list_nodes or isinstance(s, BNode):          # list internals / anonymous class parts
      continue
    lines.append(f'{_short(s, g)} {_short(p, g)} {_short(o, g)}')
  return sorted(lines) or ['(part of a class definition: an owl:Restriction)']


def format_proof(proofs: list, indent: int = 0) -> str:
  """The first proof as indented text: INFERRED facts, and the ASSERTED facts / axioms behind them.

  Stardog may return several alternative proofs (e.g. Pancakes is a DairyRecipe because of the
  butter *and* because of the milk); only the first is shown.
  """
  out = []
  for proof in proofs[:1] if indent == 0 else proofs:
    if 'expression' not in proof:                         # a group of alternative proofs: take the first
      out.append(format_proof(proof.get('children', [])[:1], indent))
      continue
    lines = _statements(proof['expression'])
    pad = '    ' * indent
    out.append(f"{pad}{proof['status']}: {lines[0]}")
    out.extend(f"{pad}{' ' * (len(proof['status']) + 2)}{line}" for line in lines[1:])
    if proof.get('children'):
      out.append(format_proof(proof['children'], indent + 1))
  return '\n'.join(o for o in out if o)
