"""Publish .rq files as Stardog stored queries, and remove them again (Chapter 13).

    names = stored_queries.publish('edugraph', prefix='tutorial_edugraph_')
    sparql.run_stored(conn, 'tutorial_edugraph_prerequisite_gaps', graphs=..., threshold=50)
"""
from kg import client
from kg.sparql import QUERY_DIR


def list_names(prefix: str = '') -> list[str]:
  with client.admin() as admin:
    return sorted(q.name for q in admin.stored_queries() if q.name.startswith(prefix))


def publish(folder: str, prefix: str) -> list[str]:
  """Store every src/kg/queries/<folder>/*.rq on the server as <prefix><file name>. Replaces existing ones."""
  settings = client.load_settings()
  names = []
  with client.admin(settings) as admin:
    existing = {q.name for q in admin.stored_queries()}
    for path in sorted((QUERY_DIR / folder).glob('*.rq')):
      name = prefix + path.stem
      if name in existing:
        admin.stored_query(name).delete()          # pystardog has no update: delete and re-create
      admin.new_stored_query(name, path.read_text(encoding='utf-8'), {'database': settings.database})
      names.append(name)
  return names


def remove(prefix: str) -> list[str]:
  """Delete every stored query whose name starts with `prefix`."""
  removed = list_names(prefix)
  with client.admin() as admin:
    for name in removed:
      admin.stored_query(name).delete()
  return removed
