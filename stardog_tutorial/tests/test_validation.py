"""The recipe SHACL shapes accept good recipes and reject bad ones."""
import stardog

from kg import client, recipes, validation
from conftest import ROOT, unique

GOOD = {'id': 'R90', 'name': 'Test Salad', 'cuisine': 'Italian', 'prep_minutes': 10, 'servings': 2,
        'created': '2025-01-01', 'description': 'A test.', 'ingredients': [('tomato', 200, 'g')]}


def _validate(conn, recipe):
  shapes, data = unique('shapes'), unique('data')
  try:
    with client.transaction(conn):
      conn.add(stardog.content.File(str(ROOT / 'ontology' / 'recipes_shapes.ttl')), graph_uri=shapes)
      conn.add(stardog.content.File(str(ROOT / 'data' / 'recipes' / 'recipes.ttl')), graph_uri=data)
      conn.add(stardog.content.Raw(recipes.recipe_to_graph(recipe).serialize(format='turtle').encode(),
                                   'text/turtle'), graph_uri=data)
    return validation.validate(conn, shapes, [data])
  finally:
    with client.transaction(conn):
      conn.clear(graph_uri=shapes)
      conn.clear(graph_uri=data)


def test_good_recipe_passes(conn):
  assert _validate(conn, GOOD).ok


def test_zero_prep_time_is_a_violation(conn):
  report = _validate(conn, {**GOOD, 'prep_minutes': 0})
  assert not report.ok
  assert 'MinInclusive' in set(report.results.constraint)
