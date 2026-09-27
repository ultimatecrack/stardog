import csv
import os
from pathlib import Path

import stardog
from dotenv import load_dotenv
from rdflib import BNode, Graph, Literal, Namespace, OWL, RDF, RDFS, XSD
from rdflib.collection import Collection

load_dotenv()

conn_details = {
  'endpoint': os.environ['STARDOG_ENDPOINT'],
  'username': os.environ['STARDOG_USERNAME'],
  'password': os.environ['STARDOG_PASSWORD'],
}
DB_NAME = os.environ['STARDOG_DATABASE']

EX = Namespace('http://example.org/recipes#')
# Same naming convention Designer uses (urn:<Model>:<Model>), shown as a model in Explorer
MODEL_NAME = 'Recipe_Python'
MODEL_GRAPH = f'urn:{MODEL_NAME}:{MODEL_NAME}'
DATA_GRAPH = f'urn:{MODEL_NAME}:data'


def build_model():
  g = Graph()
  g.bind('', EX)

  for cls in ('Recipe', 'Ingredient', 'Allergen'):
    g.add((EX[cls], RDF.type, OWL.Class))
    g.add((EX[cls], RDFS.label, Literal(cls)))

  def obj_prop(name, domain, range_, label):
    g.add((EX[name], RDF.type, OWL.ObjectProperty))
    g.add((EX[name], RDFS.domain, EX[domain]))
    g.add((EX[name], RDFS.range, EX[range_]))
    g.add((EX[name], RDFS.label, Literal(label)))

  def data_prop(name, domain, label):
    g.add((EX[name], RDF.type, OWL.DatatypeProperty))
    g.add((EX[name], RDFS.domain, EX[domain]))
    g.add((EX[name], RDFS.range, XSD.string))
    g.add((EX[name], RDFS.label, Literal(label)))

  obj_prop('hasIngredient', 'Recipe', 'Ingredient', 'has ingredient')
  obj_prop('hasAllergen', 'Ingredient', 'Allergen', 'has allergen')
  obj_prop('containsAllergen', 'Recipe', 'Allergen', 'contains allergen')

  # Recipe containsAllergen = hasIngredient / hasAllergen (inferred with reasoning on)
  chain = BNode()
  Collection(g, chain, [EX.hasIngredient, EX.hasAllergen])
  g.add((EX.containsAllergen, OWL.propertyChainAxiom, chain))

  data_prop('name', 'Recipe', 'name')
  data_prop('details', 'Recipe', 'details')
  data_prop('ingredientId', 'Ingredient', 'ingredient id')
  return g


def iri(name):
  return EX[name.replace(' ', '_')]


def read_csv(name):
  with open(Path(__file__).parent / 'data' / name, newline='', encoding='utf-8') as f:
    return list(csv.DictReader(f))


def build_data():
  g = Graph()
  g.bind('', EX)

  for r in read_csv('recipes.csv'):
    recipe = iri(r['recipe_name'])
    g.add((recipe, RDF.type, EX.Recipe))
    g.add((recipe, EX.name, Literal(r['recipe_name'])))
    g.add((recipe, EX.details, Literal(r['details'])))

  for r in read_csv('ingredients.csv'):
    ing = EX[r['ingredient_id']]
    g.add((ing, RDF.type, EX.Ingredient))
    g.add((ing, EX.ingredientId, Literal(r['ingredient_id'])))
    g.add((ing, EX.name, Literal(r['ingredient_name'])))

  for r in read_csv('allergens.csv'):
    allergen = iri(r['allergen_name'])
    g.add((allergen, RDF.type, EX.Allergen))
    g.add((allergen, EX.name, Literal(r['allergen_name'])))

  for r in read_csv('recipe_ingredients.csv'):
    g.add((iri(r['recipe_name']), EX.hasIngredient, EX[r['ingredient_id']]))

  for r in read_csv('ingredient_allergens.csv'):
    g.add((EX[r['ingredient_id']], EX.hasAllergen, iri(r['allergen_name'])))

  return g


def load(conn, graph, graph_uri):
  # Always pass graph_uri: clear() without it wipes the whole database.
  conn.clear(graph_uri=graph_uri)
  conn.add(stardog.content.Raw(graph.serialize(format='turtle').encode(), content_type='text/turtle'),
           graph_uri=graph_uri)


# Register the model as a named reasoning schema, keeping any others (e.g. from Designer)
with stardog.Admin(**conn_details) as admin:
  db = admin.database(DB_NAME)
  schemas = db.get_options('reasoning.schemas')['reasoning.schemas']
  schemas = [s for s in schemas if not s.startswith(f'{MODEL_NAME}=')] + [f'{MODEL_NAME}={MODEL_GRAPH}']
  db.set_options({'reasoning.schemas': schemas})

with stardog.Connection(DB_NAME, **conn_details) as conn:
  conn.begin()
  load(conn, build_model(), MODEL_GRAPH)
  load(conn, build_data(), DATA_GRAPH)
  conn.commit()

  # Recipe allergens, inferred through the property chain
  results = conn.select("""
    PREFIX : <http://example.org/recipes#>
    SELECT ?recipe (GROUP_CONCAT(DISTINCT ?allergen; separator=", ") AS ?allergens)
    FROM <tag:stardog:api:context:all>
    { ?r :containsAllergen ?a . ?r :name ?recipe . ?a :name ?allergen . }
    GROUP BY ?recipe ORDER BY ?recipe
  """, reasoning=True, schema=MODEL_NAME)
  for row in results['results']['bindings']:
    print(row['recipe']['value'], '->', row['allergens']['value'])
