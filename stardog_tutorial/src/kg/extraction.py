"""Concept extraction with a local LLM (Ollama) and entity linking with embeddings (Chapter 11).

    mentions = extraction.extract(text, cache=CACHE)      # {'teaches': [...], 'requires': [...], 'mentions': [...]}
    links = extraction.link(mentions['requires'], topics) # match each mention to a known topic, or not

Ollama must be running locally (`ollama serve`) with the models pulled:
    ollama pull qwen2.5:7b ; ollama pull nomic-embed-text
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

import requests

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
EXTRACT_MODEL = 'qwen2.5:7b'
EMBED_MODEL = 'nomic-embed-text'
PROMPT_VERSION = 'v2'

PROMPT = '''You extract learning concepts from a lesson, for a curriculum knowledge graph.
Return only JSON of the form {"teaches": [...], "requires": [...], "mentions": [...]}.

- "teaches": the 1 to 3 main subjects the lesson teaches. Broad subject names such as
  "linear regression" or "pandas", never function names, code or single steps.
- "requires": up to 5 subjects the reader must already know before this lesson.
- "mentions": up to 6 other named methods, tools or concepts that appear in the lesson but are
  neither its main subject nor a prerequisite.
Use short names of 1 to 4 words, in lower case, with no explanations.

Lesson:
"""
<<TEXT>>
"""'''


def ollama_available() -> bool:
  try:
    tags = requests.get(f'{OLLAMA_URL}/api/tags', timeout=5).json()
  except requests.RequestException:
    return False
  names = {m['name'].split(':latest')[0] for m in tags.get('models', [])}
  return EXTRACT_MODEL in names and EMBED_MODEL in names


def _key(text: str, model: str) -> str:
  return hashlib.sha256(f'{model}|{PROMPT_VERSION}|{text}'.encode()).hexdigest()[:16]


def extract(text: str, model: str = EXTRACT_MODEL, cache: Path | None = None) -> dict:
  """Concept mentions by role. Results are cached per (text, model, prompt version)."""
  store = json.loads(cache.read_text(encoding='utf-8')) if cache and cache.exists() else {}
  key = _key(text, model)
  if key not in store:
    r = requests.post(f'{OLLAMA_URL}/api/generate', timeout=600, json={
      'model': model, 'prompt': PROMPT.replace('<<TEXT>>', text), 'format': 'json', 'stream': False,
      'options': {'temperature': 0, 'seed': 42}})
    r.raise_for_status()
    raw = json.loads(r.json()['response'])
    store[key] = {role: [str(m).strip() for m in raw.get(role, []) if str(m).strip()]
                  for role in ('teaches', 'requires', 'mentions')}
    if cache:
      cache.write_text(json.dumps(store, indent=2), encoding='utf-8')
  return store[key]


def embed(texts: list[str], kind: str = 'query') -> list[list[float]]:
  """Embedding vectors. nomic-embed-text expects a 'search_query:' or 'search_document:' prefix."""
  r = requests.post(f'{OLLAMA_URL}/api/embed', timeout=120,
                    json={'model': EMBED_MODEL, 'input': [f'search_{kind}: {t}' for t in texts]})
  r.raise_for_status()
  return r.json()['embeddings']


def cosine(a: list[float], b: list[float]) -> float:
  return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


def normalize(name: str) -> str:
  return re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()


CHOOSE_PROMPT = '''In a data science curriculum, a lesson refers to the concept "<<MENTION>>".
Which ONE of these curriculum topics is that concept part of? Topics: <<TOPICS>>.
Answer with JSON {"topic": "<exact topic name>"}, or {"topic": null} if none of them clearly fits.'''


def choose_topic(mention: str, topic_names: list[str], model: str = EXTRACT_MODEL, cache: Path | None = None):
  """Ask the LLM which topic (from a fixed list) a mention belongs to. Returns a name from the list, or None."""
  store = json.loads(cache.read_text(encoding='utf-8')) if cache and cache.exists() else {}
  key = 'choose:' + _key(mention + '|' + '|'.join(sorted(topic_names)), model)
  if key not in store:
    prompt = CHOOSE_PROMPT.replace('<<MENTION>>', mention).replace('<<TOPICS>>', '; '.join(sorted(topic_names)))
    r = requests.post(f'{OLLAMA_URL}/api/generate', timeout=600, json={
      'model': model, 'prompt': prompt, 'format': 'json', 'stream': False, 'options': {'temperature': 0, 'seed': 42}})
    r.raise_for_status()
    store[key] = json.loads(r.json()['response']).get('topic')
    if cache:
      cache.write_text(json.dumps(store, indent=2), encoding='utf-8')
  answer = store[key]
  return answer if answer in topic_names else None          # never trust a name that isn't in the list


class Linker:
  """Links free-text mentions to known topics.

  1. exact (normalized) name match                      -> accepted
  2. embedding similarity >= accept_threshold           -> accepted
  3. otherwise, if use_llm: the LLM picks from the list -> needs review (a person confirms)
  4. no match                                           -> a new concept candidate
  """

  def __init__(self, topics: dict[str, str], accept_threshold: float = 0.75, use_llm: bool = True,
               cache: Path | None = None):
    self.topics = topics                                  # {iri: name}
    self.accept_threshold = accept_threshold
    self.use_llm = use_llm
    self.cache = cache
    self.iris = list(topics)
    self.vectors = embed([topics[i] for i in self.iris], kind='document')
    self.by_name = {normalize(n): i for i, n in topics.items()}

  def link(self, mentions: list[str]) -> list[dict]:
    """One dict per mention: mention, iri, topic, score, best_guess, method, status."""
    if not mentions:
      return []
    results = []
    for mention, vector in zip(mentions, embed(mentions)):
      score, guess = max((cosine(vector, v), i) for v, i in zip(self.vectors, self.iris))
      result = {'mention': mention, 'iri': None, 'topic': None, 'score': round(score, 3),
                'best_guess': self.topics[guess], 'method': 'none', 'status': 'new'}
      exact = self.by_name.get(normalize(mention))
      if exact:
        result.update(iri=exact, score=1.0, method='exact', status='accepted')
      elif score >= self.accept_threshold:
        result.update(iri=guess, method='embedding', status='accepted')
      elif self.use_llm:
        name = choose_topic(mention, list(self.topics.values()), cache=self.cache)
        if name:
          result.update(iri=next(i for i, n in self.topics.items() if n == name), method='llm', status='review')
      if result['iri']:
        result['topic'] = self.topics[result['iri']]
      results.append(result)
    return results
