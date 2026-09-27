"""Ontology versioning and governance checks (Chapter 18).

    changes = governance.diff('ontology/versions/edugraph-1.0.ttl', 'ontology/edugraph.ttl')
    governance.check_version('1.0', '1.1', changes)       # is the version bump big enough?
    governance.undeclared_terms(conn, ONTOLOGY, DATA)       # vocabulary the data uses but the ontology doesn't define
    governance.deprecated_usage(conn, ONTOLOGY, DATA)       # deprecated terms still in use (data and .rq files)

Change kinds, like semantic versioning for an API:
  breaking  a term removed, or the meaning of an existing term changed (domain, range, hierarchy, disjointness)
  minor     new terms, rules or deprecations: existing data and queries keep working
  patch     documentation only (labels, comments, version info)
"""
from pathlib import Path

import pandas as pd
import stardog
from rdflib import BNode, Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from kg import sparql
from kg.sparql import QUERY_DIR

DECLARATIONS = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.TransitiveProperty, OWL.Ontology}
MEANING = {RDFS.domain, RDFS.range, RDFS.subClassOf, RDFS.subPropertyOf, OWL.disjointWith, OWL.equivalentClass,
           OWL.inverseOf}
DOCUMENTATION = {RDFS.label, RDFS.comment, OWL.versionInfo, OWL.versionIRI, OWL.priorVersion}
RULE_CONTENT = URIRef('tag:stardog:api:rule:content')
STANDARD = ('http://www.w3.org/', 'tag:stardog:')


def _load(source) -> Graph:
  return source if isinstance(source, Graph) else Graph().parse(str(source), format='turtle')


def _short(node, g: Graph) -> str:
  try:
    return g.namespace_manager.normalizeUri(node) if isinstance(node, URIRef) else str(node)
  except Exception:
    return str(node)


def diff(old, new) -> pd.DataFrame:
  """Every change between two ontology versions (files or rdflib Graphs), classified.

  Rules are blank nodes, so they are compared by their text (rule:content), not by node id.
  """
  g_old, g_new = _load(old), _load(new)
  rows = []

  def rules(g):                                   # {normalized rule text: label}
    return {' '.join(str(o).split()): str(g.value(s, RDFS.label) or '(no label)')
            for s, o in g.subject_objects(RULE_CONTENT) if isinstance(s, BNode)}

  r_old, r_new = rules(g_old), rules(g_new)
  for text in sorted(r_new.keys() - r_old.keys()):
    rows.append(('rule', 'rule added', 'minor', r_new[text]))
  for text in sorted(r_old.keys() - r_new.keys()):
    rows.append(('rule', 'rule removed', 'breaking', r_old[text]))

  def triples(g):
    return {(s, p, o) for s, p, o in g if not isinstance(s, BNode) and not isinstance(o, BNode)}

  t_old, t_new = triples(g_old), triples(g_new)
  declared_old = {s for s, o in g_old.subject_objects(RDF.type) if o in DECLARATIONS}
  declared_new = {s for s, o in g_new.subject_objects(RDF.type) if o in DECLARATIONS}
  for s in sorted(declared_new - declared_old):
    rows.append((_short(s, g_new), 'term added', 'minor', ''))
  for s in sorted(declared_old - declared_new):
    rows.append((_short(s, g_old), 'term removed', 'breaking', 'data and queries using it lose their meaning'))

  for change, triple_set, g in (('added', t_new - t_old, g_new), ('removed', t_old - t_new, g_old)):
    for s, p, o in sorted(triple_set):
      if s in (declared_new ^ declared_old):
        continue                                           # covered by 'term added/removed'
      what = f'{_short(p, g)} {_short(o, g)}'
      if p == OWL.deprecated:
        rows.append((_short(s, g), f'deprecated' if change == 'added' else 'undeprecated', 'minor', what))
      elif p in DOCUMENTATION:
        rows.append((_short(s, g), f'documentation {change}', 'patch', what[:90]))
      elif p in MEANING and change == 'removed':
        rows.append((_short(s, g), 'axiom removed', 'breaking', what))
      elif p in MEANING:
        # a new axiom on an existing term changes inferences for existing data: review it; a new
        # superclass / superproperty only adds inferences, a new domain/range/disjointness can reclassify data
        kind = 'minor' if p in (RDFS.subClassOf, RDFS.subPropertyOf) else 'breaking'
        rows.append((_short(s, g), 'axiom added', kind, what))
      elif p == RDF.type and o not in DECLARATIONS:
        rows.append((_short(s, g), f'type {change}', 'minor' if change == 'added' else 'breaking', what))
  order = {'breaking': 0, 'minor': 1, 'patch': 2}
  df = pd.DataFrame(rows, columns=['term', 'change', 'kind', 'detail'])
  return df.sort_values(['kind', 'term'], key=lambda c: c.map(order) if c.name == 'kind' else c).reset_index(drop=True)


def required_bump(changes: pd.DataFrame) -> str:
  kinds = set(changes.kind)
  return 'major' if 'breaking' in kinds else 'minor' if 'minor' in kinds else 'patch' if kinds else 'none'


def check_version(old: str, new: str, changes: pd.DataFrame) -> dict:
  """Does the version number change as much as the content? Versions look like 1.0, 1.1, 2.0.

  With major.minor versions, documentation-only (patch) changes need no new number.
  """
  (o_major, o_minor), (n_major, n_minor) = (tuple(int(x) for x in v.split('.')) for v in (old, new))
  bump = 'major' if n_major > o_major else 'minor' if (n_major, n_minor) > (o_major, o_minor) else 'none'
  needed = required_bump(changes)
  rank = {'none': 0, 'patch': 0, 'minor': 1, 'major': 2}
  return {'from': old, 'to': new, 'bump': bump, 'needed': needed, 'ok': rank[bump] >= rank[needed]}


def undeclared_terms(conn: stardog.Connection, ontology_graph: str, data_graphs: list[str]) -> pd.DataFrame:
  """Properties and classes the data uses that the ontology doesn't declare (typos, drift, forgotten terms)."""
  values = ' '.join(f'<{g}>' for g in data_graphs)
  used = sparql.run_query(conn, f'''
    SELECT ?term ?usage (COUNT(*) AS ?triples) {{
      VALUES ?g {{ {values} }}
      {{ GRAPH ?g {{ ?s ?term ?o }} FILTER(?term != <{RDF.type}>) BIND("property" AS ?usage) }}
      UNION {{ GRAPH ?g {{ ?s a ?term }} BIND("class" AS ?usage) }}
    }} GROUP BY ?term ?usage''')
  declared = set(sparql.run_query(conn, 'SELECT DISTINCT ?t { ?t a ?kind FILTER(isIRI(?t)) }', graphs=ontology_graph).t)
  missing = used[~used.term.isin(declared) & ~used.term.str.startswith(STANDARD)]
  return missing.sort_values('triples', ascending=False).reset_index(drop=True)


def deprecated_usage(conn: stardog.Connection, ontology_graph: str, data_graphs: list[str],
                     query_folder: str | None = None) -> pd.DataFrame:
  """Deprecated terms still in use: triples in the data graphs, and .rq files that mention them."""
  deprecated = list(sparql.run_query(conn, '''PREFIX owl: <http://www.w3.org/2002/07/owl#>
    SELECT ?t { ?t owl:deprecated true }''', graphs=ontology_graph).t)
  rows = []
  for t in deprecated:
    n = sparql.run_query(conn, 'SELECT (COUNT(*) AS ?n) { ?s ?p ?o }', graphs=data_graphs, p=URIRef(t)).n.iloc[0]
    local = t.rsplit('#', 1)[-1]
    queries = [p.relative_to(QUERY_DIR).with_suffix('').as_posix()
               for p in sorted((QUERY_DIR / (query_folder or '')).rglob('*.rq'))
               if f'edu:{local}' in p.read_text(encoding='utf-8') or t in p.read_text(encoding='utf-8')] if query_folder else []
    rows.append({'term': t, 'data triples': int(n), 'queries': ', '.join(queries)})
  return pd.DataFrame(rows, columns=['term', 'data triples', 'queries'])
