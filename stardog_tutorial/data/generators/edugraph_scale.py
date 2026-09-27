"""Generate a large synthetic EduGraph SIS for performance work (Chapter 15).

    from edugraph_scale import generate
    path, triples = generate(Path(tmp) / 'edugraph_scale.nt.gz', students=15_000)

Uses the same IRIs and properties as the Chapter 10 mappings, so all EduGraph queries work on it.
Seeded, so the output is always the same for the same arguments.
"""
import gzip
import random
from datetime import date, timedelta
from pathlib import Path

EDU = 'http://example.org/edu#'
BASE = 'http://example.org/edu/'
XSD = 'http://www.w3.org/2001/XMLSchema#'
COURSES = {
  'DS101': ['python-basics', 'control-flow', 'functions', 'data-structures', 'numpy', 'pandas', 'visualization'],
  'MA120': ['arithmetic', 'linear-algebra', 'calculus', 'probability', 'statistics'],
  'DB150': ['sql-basics', 'sql-joins', 'rdf-sparql', 'knowledge-graphs'],
  'ML201': ['regression', 'classification', 'model-evaluation', 'clustering', 'neural-networks'],
}
CITIES = ['Bengaluru', 'Pune', 'Berlin', 'Lagos', 'Sao Paulo', 'Toronto', 'Mumbai', 'Paris', 'Nairobi', 'Austin']


def _lit(value, datatype=None) -> str:
  text = str(value).replace('\\', '\\\\').replace('"', '\\"')
  return f'"{text}"^^<{XSD}{datatype}>' if datatype else f'"{text}"'


def generate(path: Path, students: int = 15_000, seed: int = 11) -> tuple[Path, int]:
  """Write students, enrollments and assessments as gzipped N-Triples. Returns (path, triple count)."""
  rng = random.Random(seed)
  count = 0
  path = Path(path)
  path.parent.mkdir(parents=True, exist_ok=True)
  with gzip.open(path, 'wt', encoding='utf-8') as out:
    def emit(s, p, o):
      nonlocal count
      out.write(f'<{s}> <{p}> {o} .\n')
      count += 1
    assessment = 0
    for n in range(1, students + 1):
      s = f'{BASE}student/X{n:05d}'
      emit(s, 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', f'<{EDU}Student>')
      emit(s, EDU + 'studentId', _lit(f'X{n:05d}'))
      emit(s, EDU + 'name', _lit(f'Student {n:05d}'))
      emit(s, EDU + 'city', _lit(rng.choice(CITIES)))
      emit(s, EDU + 'year', _lit(rng.choice([1, 1, 2, 2, 3]), 'integer'))
      ability = rng.gauss(68, 13)
      for course in rng.sample(sorted(COURSES), k=rng.choice([1, 2, 2, 3])):
        emit(s, EDU + 'enrolledIn', f'<{BASE}course/{course}>')
        day = date(2025, 2, 1) + timedelta(days=rng.randint(0, 200))
        for i, topic in enumerate(COURSES[course]):
          if rng.random() < 0.8:
            assessment += 1
            a = f'{BASE}assessment/X{assessment:07d}'
            emit(a, EDU + 'student', f'<{s}>')
            emit(a, EDU + 'topic', f'<{BASE}topic/{topic}>')
            emit(a, EDU + 'score', _lit(max(5, min(100, round(rng.gauss(ability - 3 * i, 12)))), 'integer'))
            emit(a, EDU + 'takenOn', _lit((day + timedelta(days=14 * i)).isoformat(), 'date'))
  return path, count


if __name__ == '__main__':
  import tempfile
  p, n = generate(Path(tempfile.gettempdir()) / 'edugraph_scale.nt.gz')
  print(f'{n:,} triples -> {p} ({p.stat().st_size / 1e6:.1f} MB)')
