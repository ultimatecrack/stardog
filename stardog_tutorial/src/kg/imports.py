"""Map CSV / JSON files to RDF with SMS2 mappings and import them into a named graph (Chapter 10)."""
from pathlib import Path

from stardog.content import ImportFile, MappingFile

from kg import client


def import_file(data_file: str | Path, mapping_file: str | Path, graph: str, replace: bool = True) -> int:
  """Import one CSV/JSON file through an SMS2 mapping into `graph`. Returns the graph's triple count.

  replace=True clears the graph first, so re-running an import doesn't mix old and new rows.
  """
  settings = client.load_settings()
  with client.connect(settings=settings) as conn:
    if replace:
      with client.transaction(conn):
        conn.clear(graph_uri=graph)
  with client.admin(settings) as admin:
    admin.import_file(settings.database, MappingFile(str(mapping_file), 'SMS2'), ImportFile(str(data_file)),
                      named_graph=graph)
  with client.connect(settings=settings) as conn:
    result = conn.select(f'SELECT (COUNT(*) AS ?n) {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}')
    return int(result['results']['bindings'][0]['n']['value'])
