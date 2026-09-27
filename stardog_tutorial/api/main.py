r"""EduGraph REST API (Chapters 13, 14 and 18): a thin FastAPI layer over SPARQL queries stored in Stardog.

Run it from the stardog_tutorial folder:
    ..\.venv\Scripts\uvicorn api.main:app --reload
then open http://127.0.0.1:8000/docs

Settings (environment variables, all optional):
    EDUGRAPH_GRAPHS         comma-separated named graphs to query (default: Chapter 13's graphs)
    EDUGRAPH_QUERY_PREFIX   prefix of the stored queries (default: tutorial_edugraph_)
    EDUGRAPH_API_KEY        if set, every request except /health needs the header  X-API-Key: <key>
    EDUGRAPH_STARDOG_USER / EDUGRAPH_STARDOG_PASSWORD
                            if set, the API connects to Stardog as this (least-privilege) user (Chapter 14)
    EDUGRAPH_POOL_SIZE      Stardog connections kept open and reused (default 4; 0 = a new one per request)
    EDUGRAPH_CACHE_SECONDS  cache query results for this many seconds (default 0 = off)       (Chapter 18)
    EDUGRAPH_LLM_CACHE      JSON file caching LLM answers for /ask (optional)                  (Chapter 18)
"""
import os
import queue
import statistics
import sys
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import pandas as pd                                                     # noqa: E402
from dataclasses import replace                                         # noqa: E402

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Request   # noqa: E402
from rdflib import URIRef                                               # noqa: E402

from kg import client, extraction, llm, sparql                          # noqa: E402

DEFAULT_GRAPHS = ['urn:tutorial:ch13:curriculum', 'urn:tutorial:ch13:sis:students',
                  'urn:tutorial:ch13:sis:enrollments', 'urn:tutorial:ch13:sis:assessments']
GRAPHS = os.environ.get('EDUGRAPH_GRAPHS', ','.join(DEFAULT_GRAPHS)).split(',')
QUERY_PREFIX = os.environ.get('EDUGRAPH_QUERY_PREFIX', 'tutorial_edugraph_')
SETTINGS = client.load_settings()
if os.environ.get('EDUGRAPH_STARDOG_USER'):
  SETTINGS = replace(SETTINGS, username=os.environ['EDUGRAPH_STARDOG_USER'],
                     password=os.environ['EDUGRAPH_STARDOG_PASSWORD'])
API_KEY = os.environ.get('EDUGRAPH_API_KEY')
POOL_SIZE = int(os.environ.get('EDUGRAPH_POOL_SIZE', '4'))
CACHE_SECONDS = float(os.environ.get('EDUGRAPH_CACHE_SECONDS', '0'))
LLM_CACHE = Path(os.environ['EDUGRAPH_LLM_CACHE']) if os.environ.get('EDUGRAPH_LLM_CACHE') else None

STUDENT = 'http://example.org/edu/student/'
TOPIC = 'http://example.org/edu/topic/'

app = FastAPI(title='EduGraph API', version='1.1',
              description='Students, topics and prerequisite gaps, served from a Stardog knowledge graph.')


# ---- connections: a small pool, because opening one costs a TLS handshake and a login ------------

_pool: queue.LifoQueue = queue.LifoQueue(maxsize=max(POOL_SIZE, 1))


@contextmanager
def pooled():
  """A connection for one request. Connections aren't thread-safe, so each request has one to itself;
  afterwards it goes back to the pool. One that failed is thrown away (it may be broken)."""
  try:
    conn = _pool.get_nowait()
  except queue.Empty:
    conn = client.connect(settings=SETTINGS)
  broken = False
  try:
    yield conn
  except HTTPException:                                  # a 404 or 422 says nothing about the connection
    raise
  except BaseException:
    broken = True
    raise
  finally:
    try:
      if broken or not POOL_SIZE:
        raise queue.Full
      _pool.put_nowait(conn)
    except queue.Full:
      conn.close()


def connection(x_api_key: str | None = Header(None, include_in_schema=False)):
  """Check the API key (if one is configured), then lend the request a Stardog connection."""
  if API_KEY and x_api_key != API_KEY:
    raise HTTPException(401, 'Missing or wrong X-API-Key header')
  with pooled() as conn:
    yield conn


def health_connection():
  with pooled() as conn:
    yield conn


# ---- metrics and cache (Chapter 18) --------------------------------------------------------------

STATS = {'started': time.time(), 'cache_hits': 0, 'cache_misses': 0,
         'routes': defaultdict(lambda: {'requests': 0, 'client_errors': 0, 'server_errors': 0,
                                        'ms': deque(maxlen=1000)})}
_cache: dict = {}


@app.middleware('http')
async def measure(request: Request, call_next):
  """Count requests and errors and time them, per route (e.g. 'GET /students/{student_id}')."""
  t0 = time.perf_counter()
  response = await call_next(request)
  ms = (time.perf_counter() - t0) * 1000
  route = request.scope.get('route')
  s = STATS['routes'][f"{request.method} {route.path if route else 'unknown'}"]
  s['requests'] += 1
  s['ms'].append(ms)
  if response.status_code >= 500:
    s['server_errors'] += 1
  elif response.status_code >= 400:
    s['client_errors'] += 1
  response.headers['X-Response-Time-ms'] = f'{ms:.0f}'
  return response


def run(conn, query: str, **params) -> list[dict]:
  """Run a stored query on the configured graphs; return JSON-ready rows (None for missing values).

  With EDUGRAPH_CACHE_SECONDS set, identical calls within that time are answered from memory.
  """
  key = (query, tuple(sorted((k, str(v)) for k, v in params.items())))
  if CACHE_SECONDS:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
      STATS['cache_hits'] += 1
      return hit[1]
    STATS['cache_misses'] += 1
  df = sparql.run_stored(conn, QUERY_PREFIX + query, graphs=GRAPHS, **params)
  rows = df.astype(object).where(pd.notna(df), None).to_dict(orient='records')
  if CACHE_SECONDS:
    _cache[key] = (time.monotonic() + CACHE_SECONDS, rows)
  return rows


# ---- endpoints ----------------------------------------------------------------------------------

@app.get('/health')
def health(conn=Depends(health_connection)):
  return {'status': 'ok', 'database': SETTINGS.database, 'triples': conn.size()}


@app.get('/topics')
def topics(conn=Depends(connection)):
  return run(conn, 'topics')


@app.get('/topics/{topic_id}/prerequisites')
def prerequisites(topic_id: str = PathParam(pattern=r'^[a-z0-9-]+$', examples=['regression']),
                  conn=Depends(connection)):
  rows = run(conn, 'topic_prerequisites', topic=URIRef(TOPIC + topic_id))
  if not rows and not any(t['id'] == topic_id for t in run(conn, 'topics')):
    raise HTTPException(404, f'No topic {topic_id!r}')
  return {'topic': topic_id, 'prerequisites': rows}


@app.get('/students/{student_id}')
def student(student_id: str = PathParam(pattern=r'^S[0-9]{3}$', examples=['S023']), conn=Depends(connection)):
  rows = run(conn, 'student_profile', student=URIRef(STUDENT + student_id))
  if not rows:
    raise HTTPException(404, f'No student {student_id!r}')
  return {'id': student_id, **rows[0]}


@app.get('/students/{student_id}/gaps')
def gaps(student_id: str = PathParam(pattern=r'^S[0-9]{3}$', examples=['S023']),
         threshold: int = Query(50, ge=0, le=100, description='Scores below this count as weak'),
         conn=Depends(connection)):
  if not run(conn, 'student_profile', student=URIRef(STUDENT + student_id)):
    raise HTTPException(404, f'No student {student_id!r}')
  rows = run(conn, 'prerequisite_gaps', student=URIRef(STUDENT + student_id), threshold=threshold)
  return {'id': student_id, 'threshold': threshold, 'gaps': rows}


@app.get('/students/{student_id}/ready')
def ready(student_id: str = PathParam(pattern=r'^S[0-9]{3}$', examples=['S023']), conn=Depends(connection)):
  """Topics the student can start now: every direct prerequisite passed (uses materialized edu:passed)."""
  if not run(conn, 'student_profile', student=URIRef(STUDENT + student_id)):
    raise HTTPException(404, f'No student {student_id!r}')
  return {'id': student_id, 'ready': run(conn, 'ready_topics', student=URIRef(STUDENT + student_id))}


@app.get('/courses')
def courses(conn=Depends(connection)):
  return run(conn, 'course_performance')


_rag = {}


@app.get('/ask')
def ask(question: str = Query(..., min_length=5, max_length=300, examples=['What should I learn before neural networks?']),
        conn=Depends(connection)):
  """Answer a question about the curriculum with GraphRAG (Chapter 16): grounded in graph facts only."""
  if not extraction.ollama_available():
    raise HTTPException(503, 'The language model is not available')
  if 'rag' not in _rag:                                  # built on first use: embeds every entity label once
    _rag['rag'] = llm.GraphRAG(conn, GRAPHS, None, 'edugraph/graphrag_entities', 'edugraph/graphrag_facts', cache=LLM_CACHE)
  rag = _rag['rag']
  rag.conn = conn                                        # this request's connection
  result = rag.ask(question, k=4)
  return {'question': question, 'answer': result['answer'],
          'sources': [label for _, label, _ in result['retrieved']], 'facts_used': len(result['facts'])}


@app.get('/metrics')
def metrics(x_api_key: str | None = Header(None, include_in_schema=False)):
  """Operational numbers for monitoring: traffic, errors, latency and cache use, per route."""
  if API_KEY and x_api_key != API_KEY:
    raise HTTPException(401, 'Missing or wrong X-API-Key header')
  routes = {}
  for name, s in STATS['routes'].items():
    ms = sorted(s['ms'])
    routes[name] = {'requests': s['requests'], 'client_errors': s['client_errors'], 'server_errors': s['server_errors'],
                    'p50_ms': round(statistics.median(ms)) if ms else None,
                    'p95_ms': round(ms[int(0.95 * (len(ms) - 1))]) if ms else None}
  lookups = STATS['cache_hits'] + STATS['cache_misses']
  return {'uptime_s': round(time.time() - STATS['started']), 'routes': routes,
          'cache': {'seconds': CACHE_SECONDS, 'hits': STATS['cache_hits'], 'misses': STATS['cache_misses'],
                    'hit_rate': round(STATS['cache_hits'] / lookups, 3) if lookups else None},
          'pool': {'size': POOL_SIZE, 'idle': _pool.qsize()}}
