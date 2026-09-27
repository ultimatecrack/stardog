"""SHACL validation with Stardog, and a validation gate for loading data.

    report = validation.validate(conn, SHAPES_GRAPH, [DATA_GRAPH])
    report.ok, report.results            # no violations?  DataFrame of findings

    report = validation.load_validated(conn, stardog.content.File('batch.ttl'),
                                       target=DATA_GRAPH, shapes=SHAPES_GRAPH)
"""
from dataclasses import dataclass

import pandas as pd
import stardog
from rdflib import BNode, Graph, Namespace

from kg import client

SH = Namespace('http://www.w3.org/ns/shacl#')
COLUMNS = ['severity', 'focus', 'path', 'value', 'message', 'constraint']


@dataclass
class Report:
  conforms: bool              # SHACL's verdict: False if there is ANY result, even a warning
  results: pd.DataFrame       # one row per finding
  turtle: str = ''            # the raw SHACL validation report

  def count(self, severity: str) -> int:
    return int((self.results.severity == severity).sum())

  @property
  def ok(self) -> bool:
    """True when there are no Violations (warnings and infos are allowed)."""
    return self.count('Violation') == 0

  def summary(self) -> str:
    return (f"{self.count('Violation')} violation(s), {self.count('Warning')} warning(s), "
            f"{self.count('Info')} info(s)")


def _short(node) -> str:
  if node is None:
    return ''
  if isinstance(node, BNode):
    return '(path)'
  text = str(node)
  return text.rsplit('/', 1)[-1].rsplit('#', 1)[-1] if text.startswith('http') else text


def _value(node) -> str:
  if node is None:
    return ''
  return '(blank node)' if isinstance(node, BNode) else str(node)


def parse_report(turtle: str) -> Report:
  g = Graph().parse(data=turtle, format='turtle')
  conforms = str(next(g.objects(None, SH.conforms), 'true')).lower() == 'true'
  rows = []
  for r in g.objects(None, SH.result):
    rows.append({
      'severity': _short(g.value(r, SH.resultSeverity)) or 'Violation',
      'focus': str(g.value(r, SH.focusNode)),
      'path': _short(g.value(r, SH.resultPath)),
      'value': _value(g.value(r, SH.value)),
      'message': str(g.value(r, SH.resultMessage) or ''),
      'constraint': _short(g.value(r, SH.sourceConstraintComponent)).replace('ConstraintComponent', ''),
    })
  order = {'Violation': 0, 'Warning': 1, 'Info': 2}
  df = pd.DataFrame(rows, columns=COLUMNS)
  df = df.sort_values(['severity', 'focus', 'path'], key=lambda c: c.map(order) if c.name == 'severity' else c)
  return Report(conforms, df.reset_index(drop=True), turtle)


def validate(conn: stardog.Connection, shapes: str, graphs: list[str], limit: int = 1000) -> Report:
  """Validate the data in `graphs` (merged) against the shapes stored in graph `shapes`."""
  params = [('shacl.shape.graphs', shapes), ('countLimit', str(limit))] + [('graph-uri', g) for g in graphs]
  return parse_report(conn.client.post('/icv/report', params=params).text)


def _subjects(conn: stardog.Connection, graph: str) -> set[str]:
  rows = conn.select(f'SELECT DISTINCT ?s {{ GRAPH <{graph}> {{ ?s ?p ?o  FILTER(isIRI(?s)) }} }}')
  return {b['s']['value'] for b in rows['results']['bindings']}


def load_validated(conn: stardog.Connection, content, target: str, shapes: str,
                   reference: tuple[str, ...] = (), staging: str | None = None) -> Report:
  """The validation gate: stage `content`, validate it, and only then add it to `target`.

  The batch is validated together with `target` (and any `reference` graphs), so it may refer to
  things that already exist, e.g. new recipes using known ingredients. Only findings about
  resources in the batch count. If there is no Violation, the batch is added to `target` in one
  transaction; otherwise nothing changes. The staging graph is always removed.
  """
  staging = staging or f'{target}:staging'
  with client.transaction(conn):
    conn.clear(graph_uri=staging)
    conn.add(content, graph_uri=staging)
  try:
    report = validate(conn, shapes, [staging, target, *reference])
    in_batch = report.results.focus.isin(_subjects(conn, staging))
    report = Report(report.conforms and bool(in_batch.all()), report.results[in_batch].reset_index(drop=True),
                    report.turtle)
    if report.ok:
      with client.transaction(conn):
        conn.update(f'ADD <{staging}> TO <{target}>')
  finally:
    with client.transaction(conn):
      conn.clear(graph_uri=staging)
  return report
