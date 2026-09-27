"""IRI conventions and RDF conversion for the Recipes dataset (see Chapter 3)."""
import re

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SKOS, XSD

REC = Namespace('http://example.org/recipes#')
RECIPE = Namespace('http://example.org/recipes/recipe/')
INGREDIENT = Namespace('http://example.org/recipes/ingredient/')
CATEGORY = Namespace('http://example.org/recipes/category/')
ALLERGEN = Namespace('http://example.org/recipes/allergen/')
USER = Namespace('http://example.org/recipes/user/')
RATING = Namespace('http://example.org/recipes/rating/')

PREFIXES = {'rec': REC, 'recipe': RECIPE, 'ingredient': INGREDIENT, 'category': CATEGORY,
            'allergen': ALLERGEN, 'user': USER, 'rating': RATING, 'skos': SKOS}


def slug(text: str) -> str:
  return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def new_graph() -> Graph:
  g = Graph()
  for prefix, ns in PREFIXES.items():
    g.bind(prefix, ns)
  return g


def recipe_iri(recipe: dict) -> URIRef:
  return RECIPE[slug(recipe['name'])]


def recipe_to_graph(recipe: dict) -> Graph:
  """One recipe as RDF.

  recipe = {'id': 'R15', 'name': 'Masala Omelette', 'name_fr': 'Omelette masala',
            'cuisine': 'Indian', 'prep_minutes': 15, 'servings': 1, 'created': '2025-12-01',
            'description': '...',
            'ingredients': [('egg', 3, 'piece'), ('onion', 1, 'piece')]}   # ingredient slugs
  Optional keys: name_fr, created, description.
  """
  g = new_graph()
  r = recipe_iri(recipe)
  g.add((r, RDF.type, REC.Recipe))
  g.add((r, REC.recipeId, Literal(recipe['id'])))
  g.add((r, REC.name, Literal(recipe['name'], lang='en')))
  if recipe.get('name_fr'):
    g.add((r, REC.name, Literal(recipe['name_fr'], lang='fr')))
  g.add((r, REC.cuisine, Literal(recipe['cuisine'])))
  g.add((r, REC.prepMinutes, Literal(int(recipe['prep_minutes']))))
  g.add((r, REC.servings, Literal(int(recipe['servings']))))
  if recipe.get('created'):
    g.add((r, REC.created, Literal(recipe['created'], datatype=XSD.date)))
  if recipe.get('description'):
    g.add((r, REC.description, Literal(recipe['description'], lang='en')))
  for ingredient, quantity, unit in recipe['ingredients']:
    ing, line = INGREDIENT[ingredient], BNode()
    g.add((r, REC.hasIngredient, ing))
    g.add((r, REC.hasIngredientLine, line))
    g.add((line, RDF.type, REC.IngredientLine))
    g.add((line, REC.ingredient, ing))
    g.add((line, REC.quantity, Literal(quantity, datatype=XSD.decimal)))
    g.add((line, REC.unit, Literal(unit)))
  return g
