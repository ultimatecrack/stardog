"""Read and change database options (Chapter 12+).

Some options (e.g. search.enabled, spatial.enabled) can only change while the database is
offline. set_options() tries online first, then briefly takes the database offline, and always
brings it back online.
"""
import stardog

from kg import client


def get_options(*names: str) -> dict:
  with client.admin() as admin:
    return admin.database(client.load_settings().database).get_options(*names)


def set_options(options: dict) -> dict:
  """Apply `options`; returns their previous values so they can be restored later."""
  with client.admin() as admin:
    db = admin.database(client.load_settings().database)
    previous = db.get_options(*options)
    changes = {k: v for k, v in options.items() if previous.get(k) != v}
    if not changes:
      return previous
    try:
      db.set_options(changes)
    except stardog.exceptions.StardogException as e:
      if 'while the database' not in str(e):
        raise
      db.offline()                       # the database is unavailable to everyone for a moment
      try:
        db.set_options(changes)
      finally:
        db.online()
    return previous
