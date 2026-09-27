"""Measure queries: benchmarks, plans and profiles (Chapter 15)."""
import statistics
import time

import pandas as pd
import stardog


def bench(conn: stardog.Connection, query: str, graphs=None, runs: int = 3, **kwargs) -> dict:
  """Run a SELECT `runs` times after one warm-up; return median/min seconds and the row count."""
  params = {'default_graph_uri': graphs} if graphs else {}
  conn.select(query, **params, **kwargs)                                  # warm-up
  times, rows = [], None
  for _ in range(runs):
    start = time.perf_counter()
    result = conn.select(query, **params, **kwargs)
    times.append(time.perf_counter() - start)
    rows = len(result['results']['bindings'])
  return {'median_s': round(statistics.median(times), 3), 'min_s': round(min(times), 3), 'rows': rows}


def compare(conn: stardog.Connection, queries: dict[str, str], graphs=None, runs: int = 3) -> pd.DataFrame:
  """Benchmark several named queries into one table."""
  return pd.DataFrame({name: bench(conn, q, graphs, runs) for name, q in queries.items()}).T


def plan(conn: stardog.Connection, query: str, graphs=None, profile: bool = False) -> str:
  """The query plan (profile=True: run the query and report time and memory per operator)."""
  data = {'query': query}
  if graphs:
    data['default-graph-uri'] = graphs
  if profile:
    data['profile'] = 'true'
  text = conn.client.post('/explain', data=data, headers={'Accept': 'text/plain'}).text
  return '\n'.join(line for line in text.splitlines() if line.strip() and not line.startswith('prefix '))
