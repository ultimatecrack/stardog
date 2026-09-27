"""The EduGraph API: API key, validation, 404s and answers, against temporary graphs and stored queries."""
import importlib
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from kg import stored_queries

KEY = 'test-key'


@pytest.fixture(scope='module')
def api(edugraph):
  prefix = f'test_{uuid.uuid4().hex[:6]}_'
  stored_queries.publish('edugraph', prefix)
  os.environ.update({'EDUGRAPH_GRAPHS': ','.join(edugraph.values()), 'EDUGRAPH_QUERY_PREFIX': prefix,
                     'EDUGRAPH_API_KEY': KEY})
  import api.main
  app = importlib.reload(api.main).app          # re-read the environment
  yield TestClient(app)
  stored_queries.remove(prefix)
  for k in ('EDUGRAPH_GRAPHS', 'EDUGRAPH_QUERY_PREFIX', 'EDUGRAPH_API_KEY'):
    os.environ.pop(k, None)


def test_health_needs_no_key(api):
  assert api.get('/health').status_code == 200


def test_key_is_required(api):
  assert api.get('/students/S023').status_code == 401
  assert api.get('/students/S023', headers={'X-API-Key': 'wrong'}).status_code == 401


def test_student_gaps(api):
  r = api.get('/students/S023/gaps', headers={'X-API-Key': KEY})
  assert r.status_code == 200
  assert [g['weak_topic'] for g in r.json()['gaps']] == ['Statistics']


@pytest.mark.parametrize('url, status', [('/students/S999', 404), ('/students/bob', 422),
                                         ('/students/S023/gaps?threshold=500', 422), ('/topics/nope/prerequisites', 404)])
def test_bad_requests(api, url, status):
  assert api.get(url, headers={'X-API-Key': KEY}).status_code == status


def test_metrics_count_requests(api):
  assert api.get('/metrics').status_code == 401
  api.get('/topics', headers={'X-API-Key': KEY})
  m = api.get('/metrics', headers={'X-API-Key': KEY}).json()
  assert m['routes']['GET /topics']['requests'] >= 1
  assert m['routes']['GET /students/{student_id}']['client_errors'] >= 1       # the 401s and 404s above
