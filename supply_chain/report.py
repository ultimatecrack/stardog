"""Turn the graph algorithm results stored in Stardog into supply chain insights."""
import os
from collections import defaultdict

import stardog
from dotenv import load_dotenv

load_dotenv()

conn_details = {
  'endpoint': os.environ['STARDOG_ENDPOINT'],
  'username': os.environ['STARDOG_USERNAME'],
  'password': os.environ['STARDOG_PASSWORD'],
}
DB_NAME = os.environ['STARDOG_DATABASE']

PREFIX = """
PREFIX sc: <http://example.org/supplychain#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""


DATA_GRAPH = 'urn:SupplyChain:data'


def select(conn, algorithm, prop, extra=''):
  # Name both graphs explicitly. Querying the union of every graph instead would also pick up
  # the tutorial's what-if results, mixing two scenarios into one table.
  query = f"""{PREFIX}
  SELECT ?id ?name ?type ?region ?value
  WHERE {{
    GRAPH <urn:SupplyChain:analytics:{algorithm}> {{ ?f sc:{prop} ?value }}
    GRAPH <{DATA_GRAPH}> {{ ?f sc:name ?name ; sc:region ?region ; rdf:type ?t }}
    BIND(STRAFTER(STR(?f), '#') AS ?id)
    BIND(STRAFTER(STR(?t), '#') AS ?type)
  }} {extra}"""
  rows = conn.select(query)['results']['bindings']
  return [{k: v['value'] for k, v in r.items()} for r in rows]


def groups(rows):
  out = defaultdict(list)
  for r in rows:
    out[r['value']].append(r)
  return sorted(out.values(), key=len, reverse=True)


def title(text):
  print(f'\n=== {text} ===')


with stardog.Connection(DB_NAME, **conn_details) as conn:
  title('PageRank: most critical facilities (disruption here hurts the most)')
  rows = select(conn, 'PageRank', 'pageRank', 'ORDER BY DESC(xsd:double(?value)) LIMIT 8')
  for r in rows:
    print(f"  {float(r['value']):7.3f}  {r['id']:4} {r['name']} ({r['type']})")

  title('Connected Components: independent networks')
  for i, members in enumerate(groups(select(conn, 'ConnectedComponents', 'component')), 1):
    regions = sorted({m['region'] for m in members})
    print(f'  Network {i}: {len(members)} facilities, regions: {", ".join(regions)}')

  title('Strongly Connected Components: closed loops (goods can come back around)')
  loops = [g for g in groups(select(conn, 'StronglyConnectedComponents', 'stronglyConnectedComponent'))
           if len(g) > 1]
  for members in loops:
    print('  Loop: ' + ', '.join(f"{m['id']} ({m['type']})" for m in members))
  if not loops:
    print('  No loops: every flow is one-way')

  title('Label Propagation: logistics communities')
  for i, members in enumerate(groups(select(conn, 'LabelPropagation', 'community')), 1):
    print(f'  Community {i}: ' + ', '.join(m['id'] for m in sorted(members, key=lambda m: m['id'])))

  title('Triangle Count: route redundancy')
  rows = select(conn, 'TriangleCount', 'triangleCount', 'ORDER BY DESC(xsd:long(?value)) ?id')
  redundant = [r for r in rows if int(r['value']) > 0]
  print('  Facilities with a backup path (in at least one triangle):')
  for r in redundant:
    print(f"    {r['value']:>2}  {r['id']:4} {r['name']}")
  exposed = [r for r in rows if int(r['value']) == 0 and r['type'] in ('Port', 'DistributionCenter', 'Factory')]
  print('  Hubs with no triangle (single points of failure): ' + ', '.join(r['id'] for r in exposed))
