"""Run SPARQL stored in .rq files and get pandas DataFrames back.

    from kg import sparql

    sparql.run_query(conn, 'recipes/quick_recipes', graphs=G, max_minutes=30)
    sparql.list_queries('recipes')

Queries live in src/kg/queries/<folder>/<name>.rq. They contain no FROM clause: the graphs are
passed with `graphs=` (the SPARQL protocol's default-graph-uri), so the same file works on any
graph and can be pasted into Studio as it is.
"""
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
import stardog
from rdflib import Graph, Literal, URIRef

QUERY_DIR = Path(__file__).parent / 'queries'
_NAME = re.compile(r'^[\w/-]+$')


def load_query(name: str) -> str:
  """The text of src/kg/queries/<name>.rq."""
  path = QUERY_DIR / f'{name}.rq'
  if not path.exists():
    raise FileNotFoundError(f'No query {name!r}: expected {path}')
  return path.read_text(encoding='utf-8')


def _text(query: str) -> str:
  """A query name ('recipes/quick_recipes') or the SPARQL text itself."""
  return load_query(query) if _NAME.match(query) else query


def term(value) -> str:
  """A Python value as a SPARQL term for `bindings`.

  str -> "text" (escaped), int/float/bool/date -> typed literal, rdflib URIRef/Literal as is.
  rdflib does the escaping, so values can't break out of the literal (see Chapter 6).
  """
  if isinstance(value, (URIRef, Literal)):
    return value.n3()
  return Literal(value).n3()


def _python(binding: dict):
  """One SPARQL JSON result value as a Python value, using its datatype."""
  if binding['type'] == 'uri':
    return binding['value']
  if binding['type'] == 'bnode':
    return '_:' + binding['value']
  if 'datatype' in binding:
    value = Literal(binding['value'], datatype=URIRef(binding['datatype'])).toPython()
    return float(value) if isinstance(value, Decimal) else value
  return binding['value']                        # plain or language-tagged string


def to_df(result: dict) -> pd.DataFrame:
  """SPARQL JSON results -> DataFrame with typed columns."""
  columns = result['head']['vars']
  rows = [{c: _python(b[c]) if c in b else None for c in columns}
          for b in result['results']['bindings']]
  return pd.DataFrame(rows, columns=columns)


def _options(graphs, params, kwargs):
  if graphs is not None:
    kwargs['default_graph_uri'] = graphs if isinstance(graphs, str) else list(graphs)
  if params:
    kwargs['bindings'] = {name: term(value) for name, value in params.items()}
  return kwargs


def run_query(conn: stardog.Connection, query: str, graphs=None, *, reasoning=False, schema=None,
              limit=None, **params) -> pd.DataFrame:
  """Run a SELECT (by .rq name or text) and return a typed DataFrame.

  graphs: one graph IRI or a list of them to query (merged).
  reasoning/schema: reason with the named model `schema` (Chapters 7-8).
  **params: values for query variables, e.g. max_minutes=30 binds ?max_minutes.
  """
  kwargs = _options(graphs, params, {'reasoning': reasoning or None, 'schema': schema, 'limit': limit})
  return to_df(conn.select(_text(query), **kwargs))


def run_stored(conn: stardog.Connection, name: str, graphs=None, *, reasoning=False, schema=None,
               limit=None, **params) -> pd.DataFrame:
  """Run a query stored on the Stardog server under `name` (Chapter 13), with the same options as run_query."""
  kwargs = _options(graphs, params, {'reasoning': reasoning or None, 'schema': schema, 'limit': limit})
  return to_df(conn.select(name, **kwargs))


def ask(conn: stardog.Connection, query: str, graphs=None, *, reasoning=False, schema=None, **params) -> bool:
  """Run an ASK query."""
  return conn.ask(_text(query), **_options(graphs, params, {'reasoning': reasoning or None, 'schema': schema}))


def construct(conn: stardog.Connection, query: str, graphs=None, **params) -> Graph:
  """Run a CONSTRUCT or DESCRIBE query and return the triples as an rdflib Graph."""
  data = conn.graph(_text(query), content_type='text/turtle', **_options(graphs, params, {}))
  return Graph().parse(data=data, format='turtle')


def list_queries(folder: str = '') -> pd.DataFrame:
  """Catalogue of .rq files: name, description (first comment line) and parameters."""
  rows = []
  for path in sorted((QUERY_DIR / folder).rglob('*.rq')):
    comments = [l[1:].strip() for l in path.read_text(encoding='utf-8').splitlines() if l.startswith('#')]
    params = next((c.split(':', 1)[1].strip() for c in comments if c.lower().startswith('parameters:')), '')
    rows.append({'query': path.relative_to(QUERY_DIR).with_suffix('').as_posix(),
                 'description': comments[0] if comments else '',
                 'parameters': params})
  return pd.DataFrame(rows, columns=['query', 'description', 'parameters'])
