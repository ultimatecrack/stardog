"""Idempotent writes: replace or delete everything a graph says about one resource."""
import stardog
from rdflib import Graph, URIRef

from kg import client
from kg.sparql import term

# Everything about ?s in the graph, plus the triples of blank nodes it points to
# (e.g. ingredient lines), so they don't linger or pile up as duplicates.
_DELETE_RESOURCE = '''
DELETE {{ GRAPH <{graph}> {{ ?s ?p ?o . ?o ?p2 ?o2 . }} }}
WHERE  {{ GRAPH <{graph}> {{ ?s ?p ?o  OPTIONAL {{ ?o ?p2 ?o2  FILTER(isBlank(?o)) }} }} }}
'''


def delete_resource(conn: stardog.Connection, graph: str, subject: URIRef) -> None:
  """Delete the resource's triples (and its blank nodes). Call inside a transaction."""
  conn.update(_DELETE_RESOURCE.format(graph=graph), bindings={'s': term(subject)})


def replace_resource(conn: stardog.Connection, graph: str, subject: URIRef, description: Graph) -> dict:
  """Upsert: replace what `graph` says about `subject` with `description`, atomically.

  Running it again with the same description changes nothing overall (idempotent).
  Returns the commit's {'added': n, 'removed': n}.
  """
  with client.transaction(conn) as stats:
    delete_resource(conn, graph, subject)
    conn.add(stardog.content.Raw(description.serialize(format='turtle').encode(), 'text/turtle'),
             graph_uri=graph)
  return stats
