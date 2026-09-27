"""Run Stardog graph algorithms on the supply chain with the Stardog Spark connector.

Each algorithm reads the facility -> facility `shipsTo` edges and writes one value per
facility back to Stardog, into its own named graph.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import stardog
from dotenv import load_dotenv

load_dotenv()

conn_details = {
  'endpoint': os.environ['STARDOG_ENDPOINT'],
  'username': os.environ['STARDOG_USERNAME'],
  'password': os.environ['STARDOG_PASSWORD'],
}
DB_NAME = os.environ['STARDOG_DATABASE']

ROOT = Path(__file__).resolve().parent.parent
# The connector jar bundles Spark 3.5, so it runs with plain `java -jar` (no Spark install needed)
CONNECTOR_JAR = ROOT / 'tools' / 'stardog-spark-connector-3.3.0.jar'

# The jar's bundled Scala 2.12.12 fails on Java 17, so use the portable Java 11 in tools/
JAVA = next((ROOT / 'tools').glob('jdk-11*')) / 'bin' / 'java'
JAVA_OPTS = ['-Dspark.master=local[*]']

# Spark on Windows needs Hadoop's winutils.exe/hadoop.dll (tools/hadoop/bin)
HADOOP_HOME = ROOT / 'tools' / 'hadoop'
ENV = {**os.environ, 'HADOOP_HOME': str(HADOOP_HOME),
       'PATH': f"{HADOOP_HOME / 'bin'}{os.pathsep}{os.environ['PATH']}"}

SC = 'http://example.org/supplychain#'
EDGES_QUERY = (f'construct {{ ?s <{SC}shipsTo> ?o }} '
               f'from <urn:SupplyChain:data> where {{ ?s <{SC}shipsTo> ?o }}')

# algorithm name -> (output property, iterations)
ALGORITHMS = {
  'PageRank': ('pageRank', 20),
  'ConnectedComponents': ('component', 10),
  'StronglyConnectedComponents': ('stronglyConnectedComponent', 10),
  'LabelPropagation': ('community', 10),
  'TriangleCount': ('triangleCount', 1),
}


def output_graph(algorithm):
  return f'urn:SupplyChain:analytics:{algorithm}'


def run(algorithm, prop, iterations):
  params = [
    f'algorithm.name={algorithm}',
    f'algorithm.iterations={iterations}',
    f'stardog.server={conn_details["endpoint"]}',
    f'stardog.database={DB_NAME}',
    f'stardog.username={conn_details["username"]}',
    f'stardog.password={conn_details["password"]}',
    f'stardog.query={EDGES_QUERY}',
    f'output.property={SC}{prop}',
    f'output.graph={output_graph(algorithm)}',
  ]
  cmd = [str(JAVA), *JAVA_OPTS, '-jar', str(CONNECTOR_JAR), *params]
  print(f'--- {algorithm}')
  # Run in a temp dir: Spark leaves checkpoint files behind in its working directory.
  # Not check=True: the error would echo the command line, password included.
  with tempfile.TemporaryDirectory() as workdir:
    returncode = subprocess.run(cmd, env=ENV, cwd=workdir).returncode
  if returncode != 0:
    sys.exit(f'{algorithm} failed, see the Spark output above')


if __name__ == '__main__':
  selected = sys.argv[1:] or list(ALGORITHMS)

  # Start each algorithm from an empty output graph so reruns don't duplicate values
  with stardog.Connection(DB_NAME, **conn_details) as conn:
    conn.begin()
    for algorithm in selected:
      conn.clear(graph_uri=output_graph(algorithm))
    conn.commit()

  for algorithm in selected:
    run(algorithm, *ALGORITHMS[algorithm])
