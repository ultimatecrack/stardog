"""Logical backups: export named graphs to compressed Turtle files, and restore them (Chapter 14).

A logical backup is portable (plain RDF files you can load into any Stardog, or any RDF store),
selective (only the graphs you choose) and needs no server file system access.
"""
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import stardog

from kg import client


def export_graphs(graphs: list[str], folder: Path) -> Path:
  """Write each graph to <folder>/<timestamp>/NN.ttl.gz plus a manifest.json. Returns the backup folder."""
  target = Path(folder) / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  target.mkdir(parents=True)
  manifest = []
  with client.connect() as conn:
    for i, graph in enumerate(graphs):
      data = conn.export(content_type='text/turtle', graph_uri=graph)
      name = f'{i:02d}.ttl.gz'
      with gzip.open(target / name, 'wb') as f:
        f.write(data)
      count = conn.select(f'SELECT (COUNT(*) AS ?n) {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}')
      manifest.append({'graph': graph, 'file': name,
                       'triples': int(count['results']['bindings'][0]['n']['value'])})
  (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
  return target


def restore(backup: Path) -> list[dict]:
  """Replace each graph in the backup's manifest with its saved contents, in one transaction."""
  manifest = json.loads((Path(backup) / 'manifest.json').read_text(encoding='utf-8'))
  with client.connect() as conn:
    with client.transaction(conn):
      for entry in manifest:
        conn.clear(graph_uri=entry['graph'])
        conn.add(stardog.content.File(str(Path(backup) / entry['file'])), graph_uri=entry['graph'])
  return manifest
