"""Ontology governance (Chapter 18): release checks that belong in CI."""
import stardog
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from conftest import ROOT, unique
from kg import client, governance, validation

CURRENT = ROOT / 'ontology' / 'edugraph.ttl'
PREVIOUS = ROOT / 'ontology' / 'versions' / 'edugraph-1.0.ttl'
EDU = 'http://example.org/edu#'


def test_release_bumps_the_version_enough():
  changes = governance.diff(PREVIOUS, CURRENT)
  assert 'breaking' not in set(changes.kind)
  assert governance.check_version('1.0', '1.1', changes)['ok']


def test_removing_a_term_is_breaking():
  g = Graph().parse(CURRENT)
  g.remove((URIRef(EDU + 'passed'), None, None))
  changes = governance.diff(CURRENT, g)
  assert governance.required_bump(changes) == 'major'
  assert not governance.check_version('1.1', '1.2', changes)['ok']


def test_ontology_passes_the_governance_shapes(conn):
  shapes, onto = unique('ontology-shapes'), unique('ontology')
  try:
    with client.transaction(conn):
      conn.add(stardog.content.File(str(ROOT / 'ontology' / 'ontology_shapes.ttl')), graph_uri=shapes)
      conn.add(stardog.content.File(str(CURRENT)), graph_uri=onto)
    assert validation.validate(conn, shapes, [onto]).ok
    # an undocumented, unlabelled relationship without a range fails
    bad = Graph()
    bad.add((URIRef(EDU + 'likes'), RDF.type, OWL.ObjectProperty))
    with client.transaction(conn):
      conn.add(stardog.content.Raw(bad.serialize(format='turtle').encode(), 'text/turtle'), graph_uri=onto)
    report = validation.validate(conn, shapes, [onto])
    assert not report.ok and report.count('Violation') == 2 and report.count('Warning') == 1
  finally:
    with client.transaction(conn):
      conn.clear(graph_uri=shapes)
      conn.clear(graph_uri=onto)
