import csv
import os
from pathlib import Path

import stardog
from dotenv import load_dotenv
from rdflib import Graph, Literal, Namespace, OWL, RDF, RDFS, XSD

load_dotenv()

conn_details = {
  'endpoint': os.environ['STARDOG_ENDPOINT'],
  'username': os.environ['STARDOG_USERNAME'],
  'password': os.environ['STARDOG_PASSWORD'],
}
DB_NAME = os.environ['STARDOG_DATABASE']

SC = Namespace('http://example.org/supplychain#')
MODEL_NAME = 'SupplyChain'
MODEL_GRAPH = f'urn:{MODEL_NAME}:{MODEL_NAME}'
DATA_GRAPH = f'urn:{MODEL_NAME}:data'
DATA_DIR = Path(__file__).parent / 'data'

FACILITY_TYPES = ['Supplier', 'Factory', 'Port', 'DistributionCenter', 'ReturnsCenter', 'RetailStore']


def build_model():
  g = Graph()
  g.bind('sc', SC)

  g.add((SC.Facility, RDF.type, OWL.Class))
  for cls in FACILITY_TYPES:
    g.add((SC[cls], RDF.type, OWL.Class))
    g.add((SC[cls], RDFS.subClassOf, SC.Facility))
  g.add((SC.Route, RDF.type, OWL.Class))

  def obj_prop(name, domain, range_):
    g.add((SC[name], RDF.type, OWL.ObjectProperty))
    g.add((SC[name], RDFS.domain, SC[domain]))
    g.add((SC[name], RDFS.range, SC[range_]))

  def data_prop(name, domain, range_=XSD.string):
    g.add((SC[name], RDF.type, OWL.DatatypeProperty))
    g.add((SC[name], RDFS.domain, SC[domain]))
    g.add((SC[name], RDFS.range, range_))

  # Direct facility -> facility edge: this is what the graph algorithms run on
  obj_prop('shipsTo', 'Facility', 'Facility')
  # Route details
  obj_prop('origin', 'Route', 'Facility')
  obj_prop('destination', 'Route', 'Facility')
  data_prop('mode', 'Route')
  data_prop('leadTimeDays', 'Route', XSD.integer)

  for p in ('name', 'city', 'country', 'region'):
    data_prop(p, 'Facility')

  # Algorithm outputs (written by the Spark jobs)
  data_prop('pageRank', 'Facility', XSD.double)
  for p in ('component', 'stronglyConnectedComponent', 'community'):
    data_prop(p, 'Facility', XSD.long)
  data_prop('triangleCount', 'Facility', XSD.long)

  for s in list(g.subjects(RDF.type, None)):
    g.add((s, RDFS.label, Literal(str(s).split('#')[1])))
  return g


def read_csv(name):
  with open(DATA_DIR / name, newline='', encoding='utf-8') as f:
    return list(csv.DictReader(f))


def build_data():
  g = Graph()
  g.bind('sc', SC)

  for r in read_csv('facilities.csv'):
    f = SC[r['facility_id']]
    g.add((f, RDF.type, SC[r['type']]))
    g.add((f, RDFS.label, Literal(r['name'])))
    for p in ('name', 'city', 'country', 'region'):
      g.add((f, SC[p], Literal(r[p])))

  for r in read_csv('routes.csv'):
    src, dst = SC[r['from_id']], SC[r['to_id']]
    g.add((src, SC.shipsTo, dst))
    route = SC[f"route_{r['from_id']}_{r['to_id']}"]
    g.add((route, RDF.type, SC.Route))
    g.add((route, SC.origin, src))
    g.add((route, SC.destination, dst))
    g.add((route, SC.mode, Literal(r['mode'])))
    g.add((route, SC.leadTimeDays, Literal(int(r['lead_time_days']))))
  return g


def load(conn, graph, graph_uri):
  # Always pass graph_uri: clear() without it wipes the whole database.
  conn.clear(graph_uri=graph_uri)
  conn.add(stardog.content.Raw(graph.serialize(format='turtle').encode(), content_type='text/turtle'),
           graph_uri=graph_uri)


def ensure_database(admin, name=DB_NAME):
  """Return the database, creating it first if this Stardog server doesn't have it yet."""
  if name not in [d.name for d in admin.databases()]:
    admin.new_database(name)
    print(f'Created database {name}')
  return admin.database(name)


if __name__ == '__main__':
  # Register the model as a named reasoning schema, keeping any others
  with stardog.Admin(**conn_details) as admin:
    db = ensure_database(admin)
    schemas = db.get_options('reasoning.schemas')['reasoning.schemas']
    schemas = [s for s in schemas if not s.startswith(f'{MODEL_NAME}=')] + [f'{MODEL_NAME}={MODEL_GRAPH}']
    db.set_options({'reasoning.schemas': schemas})

  with stardog.Connection(DB_NAME, **conn_details) as conn:
    conn.begin()
    load(conn, build_model(), MODEL_GRAPH)
    load(conn, build_data(), DATA_GRAPH)
    conn.commit()
    print(f'Loaded model into <{MODEL_GRAPH}> and data into <{DATA_GRAPH}>')
