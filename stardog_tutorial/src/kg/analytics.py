"""Run Stardog graph algorithms with the Stardog Spark connector (Chapter 15b).

    result = analytics.run('PageRank', edges, output_property=SC.pageRank, output_graph='urn:…:pagerank')

The connector (tools/stardog-spark-connector-3.3.0.jar in the project root) bundles Spark 3.5. It needs
Java 11 (tools/jdk-11*, because its bundled Scala 2.12.12 fails on Java 17) and, on Windows, Hadoop's
winutils.exe and hadoop.dll (tools/hadoop/bin). See the project README for download links.
"""
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from kg import client

ROOT = Path(__file__).resolve().parents[3]            # kg -> src -> stardog_tutorial -> project root
TOOLS = ROOT / 'tools'
CONNECTOR_JAR = TOOLS / 'stardog-spark-connector-3.3.0.jar'
HADOOP_HOME = TOOLS / 'hadoop'

ALGORITHMS = ('PageRank', 'ConnectedComponents', 'StronglyConnectedComponents', 'LabelPropagation', 'TriangleCount')


def java() -> Path | None:
  found = sorted(TOOLS.glob('jdk-11*'))
  return found[0] / 'bin' / ('java.exe' if os.name == 'nt' else 'java') if found else None


def tools_available() -> dict:
  return {'connector jar': CONNECTOR_JAR.exists(), 'java 11': bool(java() and java().exists()),
          'hadoop winutils': os.name != 'nt' or (HADOOP_HOME / 'bin' / 'winutils.exe').exists()}


def edges_query(predicate: str, graphs: list[str]) -> str:
  """A CONSTRUCT returning only `predicate` edges from `graphs`: what the algorithm analyses."""
  froms = ' '.join(f'from <{g}>' for g in graphs)
  return f'construct {{ ?s <{predicate}> ?o }} {froms} where {{ ?s <{predicate}> ?o }}'


def run(algorithm: str, edges: str, output_property: str, output_graph: str, iterations: int = 10) -> dict:
  """Run one algorithm; results are written to `output_graph` as (node, output_property, value)."""
  if algorithm not in ALGORITHMS:
    raise ValueError(f'Unknown algorithm {algorithm!r}; choose from {ALGORITHMS}')
  missing = [k for k, ok in tools_available().items() if not ok]
  if missing:
    raise RuntimeError(f'Missing tools: {missing}. See the project README.')
  settings = client.load_settings()
  with client.connect(settings=settings) as conn:
    with client.transaction(conn):
      conn.clear(graph_uri=output_graph)              # fresh results on every run

  params = [f'algorithm.name={algorithm}', f'algorithm.iterations={iterations}',
            f'stardog.server={settings.endpoint}', f'stardog.database={settings.database}',
            f'stardog.username={settings.username}', f'stardog.password={settings.password}',
            f'stardog.query={edges}', f'output.property={output_property}', f'output.graph={output_graph}']
  env = {**os.environ, 'HADOOP_HOME': str(HADOOP_HOME),
         'PATH': f"{HADOOP_HOME / 'bin'}{os.pathsep}{os.environ['PATH']}"}
  start = time.perf_counter()
  with tempfile.TemporaryDirectory() as workdir:       # Spark leaves checkpoint files in its working dir
    proc = subprocess.run([str(java()), '-Dspark.master=local[*]', '-jar', str(CONNECTOR_JAR), *params],
                          env=env, cwd=workdir, capture_output=True, text=True)
  log = (proc.stdout + proc.stderr).splitlines()
  if proc.returncode != 0:                             # never show the command: it contains the password
    raise RuntimeError(f'{algorithm} failed:\n' + '\n'.join(log[-20:]))
  added = next((int(m.group(1)) for line in log if (m := re.search(r'Added (\d+) triples', line))), None)
  return {'algorithm': algorithm, 'results written': added, 'seconds': round(time.perf_counter() - start, 1)}
