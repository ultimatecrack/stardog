r"""Users, roles and permissions, managed idempotently (Chapter 14).

A permission is (action, resource type, resource), e.g. ('read', 'db', 'mysampledb'),
('read', 'stored-query', 'my_query') or ('read', 'named-graph', 'mysampledb\urn:my:graph').
"""
import secrets
import string

import stardog

from kg import client


def new_password(length: int = 24) -> str:
  """A random password of letters and digits (Stardog rejects some punctuation)."""
  return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))


def _exists(fetch) -> bool:
  try:
    fetch()
    return True
  except stardog.exceptions.StardogException as e:
    if e.http_code == 404:
      return False
    raise


def ensure_role(name: str, permissions: list[tuple[str, str, str]]) -> None:
  """Create the role, or re-create it, with exactly these permissions."""
  with client.admin() as admin:
    if _exists(lambda: admin.role(name).permissions()):
      admin.role(name).delete(force=True)               # force: also detach it from users
    role = admin.new_role(name)
    for action, resource_type, resource in permissions:
      role.add_permission(action, resource_type, resource)


def ensure_user(name: str, password: str, roles: list[str]) -> None:
  """Create the user with this password and these roles, re-creating it if it exists.

  (Changing a password in place needs the *current* password on Stardog 11+, which a
  deployment script doesn't have; an admin can always delete and re-create the user.)
  """
  with client.admin() as admin:
    if _exists(lambda: admin.user(name).is_enabled()):
      admin.user(name).delete()
    user = admin.new_user(name, password)
    user.set_roles(*roles)


def drop(user: str | None = None, role: str | None = None) -> None:
  """Delete a user and/or role if they exist."""
  with client.admin() as admin:
    if user and _exists(lambda: admin.user(user).is_enabled()):
      admin.user(user).delete()
    if role and _exists(lambda: admin.role(role).permissions()):
      admin.role(role).delete(force=True)
