"""The EduGraph queries give the answers we expect, including on data made up for the test."""
import stardog
from rdflib import URIRef

from kg import client, sparql

TOPIC = 'http://example.org/edu/topic/'
STUDENT = 'http://example.org/edu/student/'


def test_regression_needs_statistics_and_its_foundations(conn, edugraph):
  rows = sparql.run_query(conn, 'edugraph/topic_prerequisites', graphs=list(edugraph.values()),
                          topic=URIRef(TOPIC + 'regression'))
  direct = set(rows[rows.direct].id)
  assert direct == {'statistics', 'linear-algebra', 'pandas'}
  assert {'probability', 'arithmetic', 'python-basics'} <= set(rows.id)      # indirect, several steps back


def _student(conn, graph, score):
  """A made-up student in ML201 with one Statistics score."""
  with client.transaction(conn):
    conn.clear(graph_uri=graph)
    conn.add(stardog.content.Raw(f'''
      @prefix edu: <http://example.org/edu#> .
      <{STUDENT}S900> a edu:Student ; edu:name "Test Student" ;
          edu:enrolledIn <http://example.org/edu/course/ML201> .
      <http://example.org/edu/assessment/T1> edu:student <{STUDENT}S900> ;
          edu:topic <{TOPIC}statistics> ; edu:score {score} .'''.encode(), 'text/turtle'), graph_uri=graph)


def test_low_statistics_score_is_a_gap_for_machine_learning(conn, edugraph, temp_graph):
  _student(conn, temp_graph, score=20)
  gaps = sparql.run_query(conn, 'edugraph/prerequisite_gaps', graphs=[edugraph['curriculum'], temp_graph],
                          threshold=50, student=URIRef(STUDENT + 'S900'))
  assert list(gaps.weak_topic) == ['Statistics']
  assert 'Linear regression' in gaps.blocks[0]


def test_good_score_is_not_a_gap(conn, edugraph, temp_graph):
  _student(conn, temp_graph, score=90)
  gaps = sparql.run_query(conn, 'edugraph/prerequisite_gaps', graphs=[edugraph['curriculum'], temp_graph],
                          threshold=50, student=URIRef(STUDENT + 'S900'))
  assert gaps.empty
