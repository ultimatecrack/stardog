"""Named reasoning schemas ("models"): what Explorer lists under Settings > Model.

A schema maps a name to one or more named graphs holding the ontology. Queries choose one
with `schema=<name>` and `reasoning=True`.
"""
from kg import client


def _db(admin):
  return admin.database(client.load_settings().database)


def list_models() -> dict:
  """{name: [graph, ...]} for every named schema in the database."""
  with client.admin() as admin:
    entries = _db(admin).get_options('reasoning.schemas')['reasoning.schemas']
  models = {}
  for entry in entries:
    name, graph = entry.split('=', 1)
    models.setdefault(name, []).append(graph)
  return models


def register_model(name: str, graph: str) -> None:
  """Add (or re-point) the named schema `name` to `graph`, keeping all other schemas."""
  with client.admin() as admin:
    db = _db(admin)
    entries = db.get_options('reasoning.schemas')['reasoning.schemas']
    entries = [e for e in entries if not e.startswith(f'{name}=')] + [f'{name}={graph}']
    db.set_options({'reasoning.schemas': entries})


def unregister_model(name: str) -> None:
  """Remove the named schema `name` (the graph and its triples are left alone)."""
  with client.admin() as admin:
    db = _db(admin)
    entries = db.get_options('reasoning.schemas')['reasoning.schemas']
    db.set_options({'reasoning.schemas': [e for e in entries if not e.startswith(f'{name}=')]})
