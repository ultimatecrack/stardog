"""EduGraph tutor tools for agents (Chapter 17): read tools, a guarded write, memory and provenance.

Every tool returns plain JSON-able data, so the same functions serve an agent loop (kg.agent)
or an MCP server (agents/mcp_server.py).
"""
import json
import re
import uuid
from datetime import datetime, timezone

import stardog
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, RDF, RDFS, XSD

from kg import sparql, validation

EDU = Namespace('http://example.org/edu#')
STUDENT = Namespace('http://example.org/edu/student/')
TOPIC = Namespace('http://example.org/edu/topic/')
PLAN = Namespace('http://example.org/edu/plan/')
RUN = Namespace('http://example.org/edu/agent-run/')
_ID = re.compile(r'^[A-Za-z0-9-]+$')


def _rows(df):
  """Rows as JSON-safe dicts (dates become ISO strings, missing values None)."""
  return json.loads(df.to_json(orient='records', date_format='iso'))


class Tutor:
  def __init__(self, conn: stardog.Connection, data_graphs: list[str], memory_prefix: str, shapes_graph: str,
               provenance_graph: str, agent_name: str):
    self.conn, self.data_graphs, self.memory_prefix = conn, data_graphs, memory_prefix
    self.shapes_graph, self.provenance_graph = shapes_graph, provenance_graph
    self.agent = URIRef(f'http://example.org/edu/agent/{agent_name}')
    self.agent_label = agent_name
    self.new_run()

  def new_run(self) -> str:
    """Start a new agent run: a new id for its memory graph and its provenance."""
    self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
    self.started = datetime.now(timezone.utc)
    self.saved_graphs = []
    return self.run_id

  # ---- read tools -----------------------------------------------------------------------------

  def student_profile(self, student_id: str) -> dict:
    if not _ID.match(student_id):
      return {'error': 'invalid student id'}
    rows = _rows(sparql.run_query(self.conn, 'edugraph/student_profile', graphs=self.data_graphs, student=STUDENT[student_id]))
    return rows[0] if rows else {'error': f'no student {student_id}'}

  def prerequisite_gaps(self, student_id: str) -> list:
    return _rows(sparql.run_query(self.conn, 'edugraph/prerequisite_gaps', graphs=self.data_graphs,
                                  student=STUDENT[student_id], threshold=50))

  def topic_prerequisites(self, topic_id: str) -> list:
    return _rows(sparql.run_query(self.conn, 'edugraph/topic_prerequisites', graphs=self.data_graphs, topic=TOPIC[topic_id]))

  def student_scores(self, student_id: str) -> list:
    return _rows(sparql.run_query(self.conn, '''PREFIX edu: <http://example.org/edu#>
      SELECT ?topic ?score { ?a edu:student ?s ; edu:topic ?t ; edu:score ?score  BIND(STRAFTER(STR(?t), "/topic/") AS ?topic) }
      ORDER BY ?score''', graphs=self.data_graphs, s=STUDENT[student_id]))

  def order_topics(self, topic_ids: list) -> dict:
    """Put topics in a valid study order: a prerequisite always has fewer prerequisites of its own than
    any topic that needs it, so sorting by that count is a topological order of the curriculum."""
    ids = [t for t in topic_ids if isinstance(t, str) and _ID.match(t)]
    if not ids:
      return {'error': 'give topic ids like statistics, pandas'}
    values = ' '.join(f'<{TOPIC[t]}>' for t in ids)                 # validated ids only
    counts = sparql.run_query(self.conn, f'''PREFIX edu: <http://example.org/edu#>
      SELECT ?t (COUNT(DISTINCT ?p) AS ?n) {{ VALUES ?t {{ {values} }} ?t a edu:Topic OPTIONAL {{ ?t edu:requires+ ?p }} }}
      GROUP BY ?t''', graphs=self.data_graphs)
    known = {str(r.t).rsplit('/', 1)[-1]: int(r.n) for r in counts.itertuples()}
    unknown = [t for t in ids if t not in known]
    ordered = sorted(dict.fromkeys(t for t in ids if t in known), key=lambda t: (known[t], t))
    return {'ordered': ordered, **({'unknown_topics': unknown} if unknown else {})}

  def previous_plans(self, student_id: str) -> list:
    """Plans saved for this student in earlier runs (oldest first): the agent's long-term memory.

    Returns only stable content (no ids or timestamps), so the agent's conversation is reproducible.
    """
    rows = _rows(sparql.run_query(self.conn, '''PREFIX edu: <http://example.org/edu#>
      SELECT ?target ?rationale (GROUP_CONCAT(?topic; separator=" -> ") AS ?steps) (MIN(?created) AS ?when) WHERE {
        { SELECT ?p ?target ?rationale ?created ?pos ?topic WHERE {
            GRAPH ?g { ?p a edu:LearningPlan ; edu:forStudent ?s ; edu:targetTopic ?t ; edu:rationale ?rationale ;
                          edu:createdAt ?created ; edu:step [ edu:position ?pos ; edu:topic ?st ] }
            FILTER(STRSTARTS(STR(?g), ?prefix))
            BIND(STRAFTER(STR(?t), "/topic/") AS ?target) BIND(STRAFTER(STR(?st), "/topic/") AS ?topic) } ORDER BY ?p ?pos }
      } GROUP BY ?p ?target ?rationale ORDER BY ?when''', s=STUDENT[student_id], prefix=self.memory_prefix))
    return [{k: v for k, v in r.items() if k != 'when'} for r in rows]

  # ---- the guarded write ------------------------------------------------------------------------

  def plan_graph(self, student_id: str, target_topic: str, steps: list[str], rationale: str) -> tuple[URIRef, Graph]:
    g = Graph()
    plan = PLAN[f'{student_id}-{self.run_id}']
    g.add((plan, RDF.type, EDU.LearningPlan))
    g.add((plan, EDU.forStudent, STUDENT[student_id]))
    g.add((plan, EDU.targetTopic, TOPIC[target_topic]))
    g.add((plan, EDU.rationale, Literal(rationale)))
    g.add((plan, EDU.createdAt, Literal(datetime.now(timezone.utc), datatype=XSD.dateTime)))
    for i, topic in enumerate(steps, 1):
      step = URIRef(f'{plan}/step-{i}')
      g.add((plan, EDU.step, step))
      g.add((step, EDU.position, Literal(i)))
      g.add((step, EDU.topic, TOPIC[topic]))
    return plan, g

  def save_plan(self, student_id: str, target_topic: str, steps: list, rationale: str) -> dict:
    """Validate the plan with SHACL against the curriculum and the student's data; write it only if valid."""
    ids = [student_id, target_topic, *steps]
    if not all(isinstance(x, str) and _ID.match(x) for x in ids):
      return {'saved': False, 'problems': ['ids must be simple codes like S023 or linear-algebra']}
    plan, g = self.plan_graph(student_id, target_topic, steps, rationale)
    graph = f'{self.memory_prefix}:{self.run_id}:{len(self.saved_graphs) + 1}'
    report = validation.load_validated(self.conn, stardog.content.Raw(g.serialize(format='turtle').encode(), 'text/turtle'),
                                       target=graph, shapes=self.shapes_graph, reference=tuple(self.data_graphs))
    problems = [f"{r.message} ({r.value.rsplit('/', 1)[-1]})" if r.value else r.message
                for r in report.results[report.results.severity == 'Violation'].itertuples()]
    if not report.ok:
      return {'saved': False, 'problems': sorted(set(problems))}
    self.saved_graphs.append(graph)                     # the graph name stays internal (see record_run)
    return {'saved': True}

  # ---- provenance --------------------------------------------------------------------------------

  def record_run(self, task: str, trace: list, answer: str) -> str:
    """Write a PROV-O record of this run: the agent, the task, every tool call, and the graphs it produced."""
    run = RUN[self.run_id]
    g = Graph()
    g.add((run, RDF.type, PROV.Activity))
    g.add((run, RDFS.label, Literal(task)))
    g.add((run, PROV.wasAssociatedWith, self.agent))
    g.add((self.agent, RDF.type, PROV.SoftwareAgent))
    g.add((self.agent, RDFS.label, Literal(self.agent_label)))
    g.add((run, PROV.startedAtTime, Literal(self.started, datatype=XSD.dateTime)))
    g.add((run, PROV.endedAtTime, Literal(datetime.now(timezone.utc), datatype=XSD.dateTime)))
    g.add((run, EDU.finalAnswer, Literal(answer)))
    for call in trace:
      node = URIRef(f"{run}/call-{call['step']}")
      g.add((run, EDU.toolCall, node))
      g.add((node, EDU.order, Literal(call['step'])))
      g.add((node, EDU.tool, Literal(call['tool'])))
      g.add((node, EDU.arguments, Literal(json.dumps(call['arguments']))))
      g.add((node, EDU.outcome, Literal(json.dumps(call['result'], default=str)[:500])))
    for graph in self.saved_graphs:
      g.add((URIRef(graph), PROV.wasGeneratedBy, run))
    with self.conn_transaction():
      self.conn.add(stardog.content.Raw(g.serialize(format='turtle').encode(), 'text/turtle'), graph_uri=self.provenance_graph)
    return str(run)

  def conn_transaction(self):
    from kg import client
    return client.transaction(self.conn)

  # ---- tool specs for agents ---------------------------------------------------------------------

  def tools(self, include_write: bool = True, include_ordering: bool = False) -> dict:
    def spec(name, description, params, required=None):
      return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': params, 'required': required if required is not None else list(params)}}}
    s = {'type': 'string'}
    tools = {
      'student_profile': {'fn': self.student_profile, 'spec': spec('student_profile', 'Profile of a student: name, courses, average score.', {'student_id': {**s, 'description': 'e.g. S023'}})},
      'student_scores': {'fn': self.student_scores, 'spec': spec('student_scores', 'All assessment scores of a student by topic id.', {'student_id': s})},
      'prerequisite_gaps': {'fn': self.prerequisite_gaps, 'spec': spec('prerequisite_gaps', 'Weak prerequisite topics of a student (score below 50) and what they block.', {'student_id': s})},
      'topic_prerequisites': {'fn': self.topic_prerequisites, 'spec': spec('topic_prerequisites', 'All prerequisites of a topic, direct and indirect. Topic ids look like regression, statistics, linear-algebra.', {'topic_id': s})},
      'previous_plans': {'fn': self.previous_plans, 'spec': spec('previous_plans', 'Learning plans saved for this student before.', {'student_id': s})},
    }
    if include_ordering:
      tools['order_topics'] = {'fn': self.order_topics, 'spec': spec(
        'order_topics', 'Put a list of topic ids into a valid study order (prerequisites first). Use it before save_plan.',
        {'topic_ids': {'type': 'array', 'items': s}})}
    if include_write:
      tools['save_plan'] = {'fn': self.save_plan, 'spec': spec(
        'save_plan', 'Save a learning plan. It is checked against the curriculum; if rejected, fix the listed problems and call again.',
        {'student_id': s, 'target_topic': s, 'steps': {'type': 'array', 'items': s, 'description': 'topic ids in study order, ending with the target topic'},
         'rationale': s})}
    return tools
