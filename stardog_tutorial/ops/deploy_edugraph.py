r"""Deploy (or tear down) the EduGraph stack on Stardog, repeatably (Chapter 14).

What 'deploy' does, in order:
  1. check the connection (the Chapter 2 setup checks)
  2. load the curriculum and import the SIS CSVs into this environment's named graphs
  3. publish the EduGraph .rq files as stored queries
  4. create a least-privilege role and API user: read the database, its graphs and its stored queries only
  5. smoke-test: run a stored query as the API user

Running it again replaces everything with the same result (idempotent).

Usage, from the stardog_tutorial folder:
    set EDUGRAPH_STARDOG_PASSWORD=<a password of letters and digits>
    ..\.venv\Scripts\python ops\deploy_edugraph.py deploy   --env demo
    ..\.venv\Scripts\python ops\deploy_edugraph.py teardown --env demo
"""
import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import stardog                                                   # noqa: E402

from kg import client, imports, security, sparql, stored_queries  # noqa: E402

SIS_FILES = ('students', 'enrollments', 'assessments')


def names(env: str) -> dict:
  """Every name an environment uses, derived from the environment's name."""
  key = env.replace('-', '_')
  graphs = {'curriculum': f'urn:edugraph:{env}:curriculum',
            **{n: f'urn:edugraph:{env}:sis:{n}' for n in SIS_FILES}}
  return {'env': env, 'graphs': graphs, 'query_prefix': f'{key}_edugraph_',
          'role': f'{key}_api_reader', 'user': f'{key}_api'}


def deploy(env: str, password: str, log=print) -> dict:
  cfg = names(env)
  settings = client.load_settings()

  failed = [c for c, ok, _ in client.check_setup(settings) if not ok]
  if failed:
    raise RuntimeError(f'Setup checks failed: {failed}')
  log('1. connection OK')

  with client.connect(settings=settings) as conn:
    with client.transaction(conn):
      conn.clear(graph_uri=cfg['graphs']['curriculum'])
      conn.add(stardog.content.File(str(ROOT / 'data' / 'edugraph' / 'curriculum.ttl')),
               graph_uri=cfg['graphs']['curriculum'])
  counts = {'curriculum': None}
  for name in SIS_FILES:
    counts[name] = imports.import_file(ROOT / 'data' / 'edugraph' / 'sis' / f'{name}.csv',
                                       ROOT / 'ontology' / 'mappings' / f'{name}.sms', cfg['graphs'][name])
  log(f'2. graphs loaded: {counts}')

  queries = stored_queries.publish('edugraph', cfg['query_prefix'])
  log(f'3. {len(queries)} stored queries published')

  permissions = [('read', 'db', settings.database)]
  permissions += [('read', 'named-graph', f"{settings.database}\\{g}") for g in cfg['graphs'].values()]
  permissions += [('read', 'stored-query', q) for q in queries]
  security.ensure_role(cfg['role'], permissions)
  security.ensure_user(cfg['user'], password, [cfg['role']])
  log(f"4. role {cfg['role']} ({len(permissions)} permissions) and user {cfg['user']} ready")

  api_settings = replace(settings, username=cfg['user'], password=password)
  with client.connect(settings=api_settings) as conn:
    topics = sparql.run_stored(conn, cfg['query_prefix'] + 'topics', graphs=list(cfg['graphs'].values()))
    try:
      conn.update(f"INSERT DATA {{ GRAPH <{cfg['graphs']['curriculum']}> {{ <urn:x> <urn:y> <urn:z> }} }}")
      raise RuntimeError('The API user can write: its permissions are too broad')
    except stardog.exceptions.StardogException as e:
      if e.http_code != 403:
        raise
  log(f'5. smoke test OK: the API user reads {len(topics)} topics and cannot write')
  return cfg


def teardown(env: str, log=print) -> dict:
  cfg = names(env)
  removed = stored_queries.remove(cfg['query_prefix'])
  security.drop(user=cfg['user'], role=cfg['role'])
  with client.connect() as conn:
    with client.transaction(conn):
      for graph in cfg['graphs'].values():
        conn.clear(graph_uri=graph)
  log(f"removed {len(removed)} stored queries, user {cfg['user']}, role {cfg['role']} "
      f"and {len(cfg['graphs'])} graphs")
  return cfg


def api_environment(cfg: dict, password: str, api_key: str) -> dict:
  """The environment variables that point the API (api/main.py) at this deployment."""
  return {'EDUGRAPH_GRAPHS': ','.join(cfg['graphs'].values()), 'EDUGRAPH_QUERY_PREFIX': cfg['query_prefix'],
          'EDUGRAPH_STARDOG_USER': cfg['user'], 'EDUGRAPH_STARDOG_PASSWORD': password,
          'EDUGRAPH_API_KEY': api_key}


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('action', choices=['deploy', 'teardown'])
  parser.add_argument('--env', default='demo', help='environment name, e.g. dev, test, prod')
  args = parser.parse_args()
  if args.action == 'deploy':
    password = os.environ.get('EDUGRAPH_STARDOG_PASSWORD')
    if not password:
      sys.exit('Set EDUGRAPH_STARDOG_PASSWORD (letters and digits) first.')
    print(json.dumps(deploy(args.env, password), indent=2))
  else:
    teardown(args.env)
