"""Shared pytest fixtures (Chapter 14). Every test works in its own temporary named graphs.

Run from the stardog_tutorial folder:   ..\.venv\Scripts\python -m pytest tests -q
"""
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

import stardog                            # noqa: E402

from kg import client, imports            # noqa: E402


def unique(name: str) -> str:
  return f'urn:tutorial:test:{uuid.uuid4().hex[:8]}:{name}'


@pytest.fixture(scope='session')
def conn():
  with client.connect() as c:
    yield c


@pytest.fixture
def temp_graph(conn):
  """An empty named graph for one test, removed afterwards."""
  graph = unique('scratch')
  yield graph
  with client.transaction(conn):
    conn.clear(graph_uri=graph)


@pytest.fixture(scope='session')
def edugraph(conn):
  """The EduGraph curriculum and SIS data, loaded once into temporary graphs for the whole session."""
  graphs = {'curriculum': unique('curriculum')}
  with client.transaction(conn):
    conn.add(stardog.content.File(str(ROOT / 'data' / 'edugraph' / 'curriculum.ttl')), graph_uri=graphs['curriculum'])
  for name in ('students', 'enrollments', 'assessments'):
    graphs[name] = unique(name)
    imports.import_file(ROOT / 'data' / 'edugraph' / 'sis' / f'{name}.csv',
                        ROOT / 'ontology' / 'mappings' / f'{name}.sms', graphs[name])
  yield graphs
  with client.transaction(conn):
    for graph in graphs.values():
      conn.clear(graph_uri=graph)
