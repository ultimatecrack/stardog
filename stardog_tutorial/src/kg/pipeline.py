"""The EduGraph production pipeline (Chapter 18).

    env = pipeline.Environment('demo')                    # every graph, model and query name derives from this
    result = pipeline.Pipeline(conn, env).run()           # ontology -> ingest -> documents -> validate -> promote
                                                          #   -> reasoning -> materialize -> publish -> smoke test
    result['status'], result['stages']

Design:
- New data is loaded into **staging** graphs. Nothing reaches the **live** graphs until the whole batch
  passes the SHACL gate; then all staged graphs are copied over in **one transaction** (promotion), so
  readers never see half an update.
- Every run is recorded in the environment's **metrics** graph: stages, timings, outcomes and graph sizes.
  The monitoring dashboard reads from there.
- Re-running is safe: every stage replaces what it produced before (idempotent).
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import stardog
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, PROV, RDF, XSD

from kg import client, extraction, imports, models, reasoning, security, sparql, stored_queries, validation

ROOT = Path(__file__).resolve().parents[2]
EDU = Namespace('http://example.org/edu#')
DOC = Namespace('http://example.org/edu/document/')
LINK = Namespace('http://example.org/edu/link/')
SIS_FILES = ('students', 'enrollments', 'assessments')
ROLE_PROPERTY = {'teaches': EDU.teaches, 'requires': EDU.requiresKnowledgeOf, 'mentions': EDU.mentions}


@dataclass
class Environment:
  """All names of one deployment (dev, test, prod, a tenant, …)."""
  name: str
  prefix: str = ''

  def __post_init__(self):
    self.prefix = self.prefix or f'urn:edugraph:{self.name}'
    key = self.name.replace('-', '_')
    self.schema = f'EduGraph_{key}'                   # reasoning model name
    self.query_prefix = f'{key}_edugraph_'            # stored queries
    self.role, self.user = f'{key}_api_reader', f'{key}_api'

  # data parts that go through staging -> live
  PARTS = ('curriculum', 'sis:students', 'sis:enrollments', 'sis:assessments', 'docs', 'review')

  def live(self, part: str) -> str:
    return f'{self.prefix}:{part}'

  def staging(self, part: str) -> str:
    return f'{self.prefix}:staging:{part}'

  @property
  def ontology(self): return f'{self.prefix}:ontology'
  @property
  def data_shapes(self): return f'{self.prefix}:shapes:data'
  @property
  def ontology_shapes(self): return f'{self.prefix}:shapes:ontology'
  @property
  def inferred(self): return f'{self.prefix}:inferred'
  @property
  def metrics(self): return f'{self.prefix}:metrics'

  @property
  def data_graphs(self) -> list[str]:
    """What applications query: the live data plus the materialized inferences."""
    return [self.live(p) for p in self.PARTS if p != 'review'] + [self.inferred]

  @property
  def all_graphs(self) -> list[str]:
    return ([self.live(p) for p in self.PARTS] + [self.staging(p) for p in self.PARTS]
            + [self.staging('ontology'), self.ontology, self.data_shapes, self.ontology_shapes, self.inferred, self.metrics])


class GateFailed(Exception):
  """A quality gate stopped the run. `report` holds the SHACL findings."""
  def __init__(self, stage: str, message: str, report=None):
    super().__init__(f'{stage}: {message}')
    self.stage, self.report = stage, report


def _count(conn, graph: str) -> int:
  return int(sparql.run_query(conn, 'SELECT (COUNT(*) AS ?n) { ?s ?p ?o }', graphs=graph).n.iloc[0])


def _add(conn, g: Graph, graph: str, replace: bool = True):
  with client.transaction(conn):
    if replace:
      conn.clear(graph_uri=graph)
    conn.add(stardog.content.Raw(g.serialize(format='turtle').encode(), 'text/turtle'), graph_uri=graph)


@dataclass
class Pipeline:
  conn: stardog.Connection
  env: Environment
  data_dir: Path = ROOT / 'data' / 'edugraph'
  ontology_file: Path = ROOT / 'ontology' / 'edugraph.ttl'
  api_password: str | None = None                   # if set, the publish stage creates a least-privilege API user
  log: callable = print
  staged: list = field(default_factory=list)

  STAGES = ('ontology', 'ingest', 'documents', 'validate', 'promote', 'reasoning', 'materialize', 'publish', 'smoke_test')

  # ---- the stages ---------------------------------------------------------------------------------

  def ontology(self) -> dict:
    """Lint the ontology with the governance shapes; only a clean ontology becomes the reasoning model."""
    env = self.env
    with client.transaction(self.conn):
      for g in (env.ontology_shapes, env.data_shapes, env.staging('ontology')):
        self.conn.clear(graph_uri=g)
      self.conn.add(stardog.content.File(str(ROOT / 'ontology' / 'ontology_shapes.ttl')), graph_uri=env.ontology_shapes)
      self.conn.add(stardog.content.File(str(ROOT / 'ontology' / 'edugraph_data_shapes.ttl')), graph_uri=env.data_shapes)
      self.conn.add(stardog.content.File(str(self.ontology_file)), graph_uri=env.staging('ontology'))
    report = validation.validate(self.conn, env.ontology_shapes, [env.staging('ontology')])
    if not report.ok:
      raise GateFailed('ontology', f"{report.count('Violation')} governance violations", report)
    with client.transaction(self.conn):
      self.conn.update(f'MOVE <{env.staging("ontology")}> TO <{env.ontology}>')
    models.register_model(env.schema, env.ontology)
    g = Graph().parse(str(self.ontology_file))
    version = g.value(g.value(predicate=RDF.type, object=OWL.Ontology), OWL.versionInfo)
    return {'version': str(version), 'triples': _count(self.conn, env.ontology), 'warnings': report.count('Warning')}

  def ingest(self) -> dict:
    """Structured sources into staging: the curriculum file and the SIS exports (CSV + SMS2 mappings)."""
    env, counts = self.env, {}
    with client.transaction(self.conn):
      self.conn.clear(graph_uri=env.staging('curriculum'))
      self.conn.add(stardog.content.File(str(self.data_dir / 'curriculum.ttl')), graph_uri=env.staging('curriculum'))
    counts['curriculum'] = _count(self.conn, env.staging('curriculum'))
    for name in SIS_FILES:
      counts[name] = imports.import_file(self.data_dir / 'sis' / f'{name}.csv',
                                         ROOT / 'ontology' / 'mappings' / f'{name}.sms', env.staging(f'sis:{name}'))
    self.staged += ['curriculum'] + [f'sis:{n}' for n in SIS_FILES]
    return counts

  def documents(self) -> dict:
    """Unstructured sources: extract concepts from the lessons (Ch 11), link them to topics.

    Accepted links become direct facts in 'docs'; uncertain ones go to the 'review' graph for a person.
    Needs Ollama; without it the documents are left as they are (the live graphs keep the last version).
    """
    if not extraction.ollama_available():
      return {'skipped': 'Ollama is not running: documents unchanged'}
    env = self.env
    topics = dict(sparql.run_query(self.conn, 'PREFIX edu: <http://example.org/edu#> SELECT ?t ?name { ?t a edu:Topic ; edu:name ?name }',
                                   graphs=env.staging('curriculum')).values)
    cache = self.data_dir / 'lessons' / 'extractions.json'
    linker = extraction.Linker(topics, accept_threshold=0.75, use_llm=True, cache=cache)
    docs, review = Graph(), Graph()
    counts = {'documents': 0, 'accepted': 0, 'review': 0, 'new concepts': 0}
    for path in sorted((self.data_dir / 'lessons').glob('*.md')):
      text = path.read_text(encoding='utf-8')
      d = DOC[path.stem]
      docs.add((d, RDF.type, EDU.Document))
      docs.add((d, EDU.title, Literal(text.splitlines()[0].lstrip('# '))))
      docs.add((d, EDU.source, Literal(f'data/edugraph/lessons/{path.name}')))
      counts['documents'] += 1
      for role, mentions in extraction.extract(text, cache=cache).items():
        for link in linker.link(mentions):
          if link['status'] == 'accepted':
            docs.add((d, ROLE_PROPERTY[role], URIRef(link['iri'])))
            counts['accepted'] += 1
          elif link['status'] == 'review':
            node = LINK[f"{path.stem}-{role}-{extraction.normalize(link['mention']).replace(' ', '-')}"]
            for p, o in [(RDF.type, EDU.TopicLink), (EDU.document, d), (EDU.role, Literal(role)),
                         (EDU.topic, URIRef(link['iri'])), (EDU.mention, Literal(link['mention'])),
                         (EDU.method, Literal(link['method'])), (EDU.status, Literal('review'))]:
              review.add((node, p, o))
            counts['review'] += 1
          else:
            counts['new concepts'] += 1
    _add(self.conn, docs, env.staging('docs'))
    _add(self.conn, review, env.staging('review'))
    self.staged += ['docs', 'review']
    return counts

  def validate(self) -> dict:
    """The quality gate: all staged data together must conform to the data shapes."""
    env = self.env
    report = validation.validate(self.conn, env.data_shapes, [env.staging(p) for p in self.staged])
    self.report = report
    if not report.ok:
      raise GateFailed('validate', f"{report.count('Violation')} violations: nothing was promoted", report)
    return {'violations': 0, 'warnings': report.count('Warning')}

  def promote(self) -> dict:
    """Copy every staged graph over its live graph in ONE transaction, then clear staging."""
    env = self.env
    ops = ' ;\n'.join(f'COPY <{env.staging(p)}> TO <{env.live(p)}>' for p in self.staged)
    with client.transaction(self.conn):
      self.conn.update(ops)
      for p in self.staged:
        self.conn.clear(graph_uri=env.staging(p))
    return {'graphs promoted': len(self.staged)}

  def reasoning(self) -> dict:
    """Check the live data is consistent with the ontology, and that the rules infer something."""
    env = self.env
    live = [env.live(p) for p in env.PARTS]
    params = [('schema', env.schema)] + [('graph-uri', g) for g in live]
    consistent = self.conn.client.get('/reasoning/consistency', params=params).text.strip().lower() == 'true'
    if not consistent:
      raise GateFailed('reasoning', 'the live data contradicts the ontology (see kg.reasoning.explain_inconsistency)')
    passed = sparql.run_query(self.conn, 'PREFIX edu: <http://example.org/edu#> SELECT (COUNT(*) AS ?n) { ?s edu:passed ?t }',
                              graphs=live, reasoning=True, schema=env.schema).n.iloc[0]
    return {'consistent': True, 'passed (inferred)': int(passed)}

  def materialize(self) -> dict:
    """Store the inferences applications need most, so they can query without reasoning (fast, cacheable).

    Materialized facts are only correct until the data changes, which is why this runs in every pipeline run.
    """
    env = self.env
    using = lambda *parts: ' '.join(f'USING <{env.live(p)}>' for p in parts)
    with client.transaction(self.conn):
      self.conn.clear(graph_uri=env.inferred)
      self.conn.update(f'''PREFIX edu: <http://example.org/edu#>
        INSERT {{ GRAPH <{env.inferred}> {{ ?t edu:dependsOn ?p }} }} {using("curriculum")}
        WHERE {{ ?t edu:requires+ ?p }}''')
      for prop, threshold in (('passed', 50), ('mastered', 80)):
        self.conn.update(f'''PREFIX edu: <http://example.org/edu#>
          INSERT {{ GRAPH <{env.inferred}> {{ ?s edu:{prop} ?t }} }} {using("sis:assessments")}
          WHERE {{ ?a edu:student ?s ; edu:topic ?t ; edu:score ?score FILTER(?score >= {threshold}) }}''')
    return {'triples': _count(self.conn, env.inferred)}

  def publish(self) -> dict:
    """Stored queries for the API, and (optionally) its least-privilege user (Chapter 14)."""
    env = self.env
    queries = stored_queries.publish('edugraph', env.query_prefix)
    result = {'stored queries': len(queries)}
    if self.api_password:
      database = client.load_settings().database
      permissions = [('read', 'db', database)]
      permissions += [('read', 'named-graph', f'{database}\\{g}') for g in env.data_graphs]
      permissions += [('read', 'stored-query', q) for q in queries]
      security.ensure_role(env.role, permissions)
      security.ensure_user(env.user, self.api_password, [env.role])
      result['api user'] = env.user
    return result

  def smoke_test(self) -> dict:
    """Run the API's key queries the way the API will (as its user, if there is one)."""
    from dataclasses import replace
    settings = client.load_settings()
    if self.api_password:
      settings = replace(settings, username=self.env.user, password=self.api_password)
    with client.connect(settings=settings) as conn:
      topics = sparql.run_stored(conn, self.env.query_prefix + 'topics', graphs=self.env.data_graphs)
      ready = sparql.run_stored(conn, self.env.query_prefix + 'ready_topics', graphs=self.env.data_graphs,
                                student=URIRef('http://example.org/edu/student/S023'))
    if len(topics) == 0 or len(ready) == 0:
      raise GateFailed('smoke_test', 'the API queries return nothing')
    return {'topics': len(topics), 'ready topics for S023': len(ready)}

  # ---- running and recording ----------------------------------------------------------------------

  def run(self, stages=None) -> dict:
    stages = stages or self.STAGES
    self.staged, self.report = [], None
    run = URIRef(f"{self.env.prefix}/run/{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}")
    started, rows, status = datetime.now(timezone.utc), [], 'ok'
    for name in stages:
      t0 = time.perf_counter()
      try:
        outcome, ok = getattr(self, name)(), True
      except GateFailed as e:
        outcome, ok, status = {'blocked': str(e)}, False, f'blocked at {name}'
      seconds = round(time.perf_counter() - t0, 2)
      rows.append({'stage': name, 'seconds': seconds, 'ok': ok, 'outcome': outcome})
      self.log(f"{'✅' if ok else '⛔'} {name:12} {seconds:6.1f}s  {outcome}")
      if not ok:
        break
    sizes = {g: _count(self.conn, g) for g in self.env.data_graphs}
    self._record(run, started, status, rows, sizes)
    return {'run': str(run), 'status': status, 'stages': pd.DataFrame(rows), 'graph sizes': sizes, 'report': self.report}

  def _record(self, run, started, status, rows, sizes):
    """A PROV-O record of the run in the metrics graph, for audits and the dashboard."""
    g = Graph()
    g.add((run, RDF.type, EDU.PipelineRun))
    g.add((run, RDF.type, PROV.Activity))
    g.add((run, EDU.environment, Literal(self.env.name)))
    g.add((run, EDU.status, Literal(status)))
    g.add((run, PROV.startedAtTime, Literal(started, datatype=XSD.dateTime)))
    g.add((run, PROV.endedAtTime, Literal(datetime.now(timezone.utc), datatype=XSD.dateTime)))
    g.add((run, PROV.used, URIRef(self.ontology_file.resolve().as_uri())))
    for i, r in enumerate(rows, 1):
      s = BNode()
      g.add((run, EDU.stage, s))
      for p, o in [(EDU.order, Literal(i)), (EDU.name, Literal(r['stage'])), (EDU.ok, Literal(r['ok'])),
                   (EDU.seconds, Literal(r['seconds'], datatype=XSD.decimal)),
                   (EDU.outcome, Literal(json.dumps(r['outcome'], default=str)))]:
        g.add((s, p, o))
    for graph, n in sizes.items():
      s = BNode()
      g.add((run, EDU.graphSize, s))
      g.add((s, EDU.graph, URIRef(graph)))
      g.add((s, EDU.triples, Literal(n)))
    _add(self.conn, g, self.env.metrics, replace=False)


def history(conn: stardog.Connection, env: Environment) -> pd.DataFrame:
  """All recorded runs of an environment, one row per stage."""
  return sparql.run_query(conn, '''PREFIX edu: <http://example.org/edu#> PREFIX prov: <http://www.w3.org/ns/prov#>
    SELECT ?run ?started ?status ?order ?stage ?ok ?seconds {
      ?run a edu:PipelineRun ; prov:startedAtTime ?started ; edu:status ?status ;
           edu:stage [ edu:order ?order ; edu:name ?stage ; edu:ok ?ok ; edu:seconds ?seconds ] }
    ORDER BY ?started ?order''', graphs=env.metrics)


def teardown(conn: stardog.Connection, env: Environment) -> dict:
  """Remove everything an environment created: graphs, model, stored queries, API user and role."""
  removed = stored_queries.remove(env.query_prefix)
  security.drop(user=env.user, role=env.role)
  if env.schema in models.list_models():
    models.unregister_model(env.schema)
  with client.transaction(conn):
    for g in env.all_graphs:
      conn.clear(graph_uri=g)
  return {'graphs': len(env.all_graphs), 'stored queries': len(removed), 'model': env.schema}
