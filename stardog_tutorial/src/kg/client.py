"""Stardog connection helpers used throughout the tutorial.

    from kg import client

    settings = client.load_settings()
    with client.admin() as admin: ...
    with client.connect() as conn: ...
    with client.transaction(conn): conn.add(...)
"""
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import requests
import stardog
from dotenv import load_dotenv

REQUIRED = ('STARDOG_ENDPOINT', 'STARDOG_USERNAME', 'STARDOG_PASSWORD', 'STARDOG_DATABASE')


@dataclass(frozen=True)
class Settings:
  endpoint: str
  username: str
  password: str
  database: str

  def conn_details(self) -> dict:
    """Keyword arguments accepted by stardog.Admin and stardog.Connection."""
    return {'endpoint': self.endpoint, 'username': self.username, 'password': self.password}

  def __repr__(self):
    # Never show the password, e.g. when a notebook displays the object
    return (f"Settings(endpoint='{self.endpoint}', username='{self.username}', "
            f"password='****', database='{self.database}')")


def find_env_file() -> Path | None:
  """The nearest .env in this file's folder or any parent (the project root)."""
  for folder in Path(__file__).resolve().parents:
    if (folder / '.env').exists():
      return folder / '.env'
  return None


def load_settings() -> Settings:
  """Read the STARDOG_* settings from .env, failing with a clear message if any are missing."""
  load_dotenv(find_env_file())
  missing = [k for k in REQUIRED if not os.environ.get(k)]
  if missing:
    raise RuntimeError(f"Missing settings: {', '.join(missing)}. "
                       'Create .env in the project root, see stardog_tutorial/00_setup/.env.example')
  return Settings(*(os.environ[k] for k in REQUIRED))


def admin(settings: Settings | None = None) -> stardog.Admin:
  """Server-level client. Contacts the server immediately, so bad credentials fail here."""
  settings = settings or load_settings()
  return stardog.Admin(**settings.conn_details())


def connect(database: str | None = None, settings: Settings | None = None) -> stardog.Connection:
  """Database-level client for STARDOG_DATABASE (or `database`)."""
  settings = settings or load_settings()
  return stardog.Connection(database or settings.database, **settings.conn_details())


@contextmanager
def transaction(conn: stardog.Connection):
  """begin() ... commit(), or roll back if the block raises.

      with client.transaction(conn) as stats:
          conn.add(...)
      print(stats)        # {'added': 42, 'removed': 0}, filled in after the commit

  When a request inside a transaction fails, Stardog aborts the transaction on the server.
  pystardog doesn't notice, so its rollback() fails and the connection still believes it is
  in a transaction. This helper resets that state so the connection stays usable.
  """
  stats = {}
  conn.begin()
  try:
    yield stats
    stats.update(conn.commit() or {})
  except Exception:
    try:
      conn.rollback()
    except stardog.exceptions.StardogException:
      conn.transaction = None   # already aborted by the server
    raise


def explain_error(error: Exception) -> str:
  """Turn common connection errors into advice."""
  if isinstance(error, requests.exceptions.ConnectionError):
    return 'Cannot reach the server: check STARDOG_ENDPOINT (https://..., port 5820) and your network.'
  code = getattr(error, 'http_code', None)
  return {
    400: 'The server rejected the request: usually a SPARQL syntax error.',
    401: 'Login failed: STARDOG_USERNAME must be a user on the Stardog server, not your cloud.stardog.com login.',
    403: 'Not allowed: your user lacks the permission, or a plan limit was reached (e.g. number of databases).',
    404: 'Not found: check the database name (STARDOG_DATABASE).',
  }.get(code, f'Unexpected error: {error}')


def check_setup(settings: Settings | None = None) -> list[tuple[str, bool, str]]:
  """Run the checks every chapter depends on. Returns (check, passed, detail) rows."""
  results = []

  def record(check, fn):
    try:
      results.append((check, True, fn()))
      return True
    except Exception as e:
      results.append((check, False, explain_error(e) if not isinstance(e, RuntimeError) else str(e)))
      return False

  if not record('Settings in .env', lambda: repr(settings or load_settings())):
    return results
  settings = settings or load_settings()

  def server_alive():
    with admin(settings) as a:
      return f'alive = {a.alive()}'
  if not record('Server reachable and login OK', server_alive):
    return results

  def database_exists():
    with admin(settings) as a:
      names = [db.name for db in a.databases()]
    if settings.database not in names:
      raise stardog.exceptions.StardogException('missing', http_code=404)
    return f"'{settings.database}' found"
  if not record('Database exists', database_exists):
    return results

  def read_access():
    with connect(settings=settings) as conn:
      return f'{conn.size()} triples (approx.)'
  record('Read access', read_access)

  def write_access():
    graph = 'urn:tutorial:setup-check'
    with connect(settings=settings) as conn:
      conn.begin()
      conn.add(stardog.content.Raw(b'<urn:a> <urn:b> <urn:c> .', 'text/turtle'), graph_uri=graph)
      conn.commit()
      conn.begin()
      conn.clear(graph_uri=graph)   # only the check's own graph
      conn.commit()
    return f'wrote and removed <{graph}>'
  record('Write access', write_access)
  return results
