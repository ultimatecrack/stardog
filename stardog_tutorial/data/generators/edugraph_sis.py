"""Generate the EduGraph 'school information system' CSV exports: students, enrollments, assessments.

Run from the project root:  .venv\\Scripts\\python stardog_tutorial\\data\\generators\\edugraph_sis.py
Seeded, so the output is always the same.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'edugraph' / 'sis'
random.seed(7)

FIRST = ['Aarav', 'Ananya', 'Ben', 'Chloe', 'Diego', 'Elena', 'Farah', 'Gabriel', 'Hana', 'Ivan', 'Jia', 'Kofi',
         'Lena', 'Mateo', 'Nina', 'Omar', 'Priya', 'Quinn', 'Rahul', 'Sara', 'Tom', 'Uma', 'Victor', 'Wen',
         'Yusuf', 'Zoe', 'Arjun', 'Bea', 'Chen', 'Dara', 'Emil', 'Freya', 'Gita', 'Hugo', 'Isla', 'Jonas']
LAST = ['Sharma', 'Patel', 'Mueller', 'Garcia', 'Okafor', 'Rossi', 'Kim', 'Nguyen', 'Silva', 'Novak', 'Haddad',
        'Jensen', 'Singh', 'Costa', 'Lindqvist', 'Mensah', 'Ivanova', 'Tanaka']
CITIES = ['Bengaluru', 'Pune', 'Berlin', 'Lagos', 'Sao Paulo', 'Toronto']
COURSES = {
  'DS101': ['python-basics', 'control-flow', 'functions', 'data-structures', 'numpy', 'pandas', 'visualization'],
  'MA120': ['arithmetic', 'linear-algebra', 'calculus', 'probability', 'statistics'],
  'DB150': ['sql-basics', 'sql-joins', 'rdf-sparql', 'knowledge-graphs'],
  'ML201': ['regression', 'classification', 'model-evaluation', 'clustering', 'neural-networks'],
}

students, enrollments, assessments = [], [], []
for n in range(1, 41):
  sid = f'S{n:03d}'
  first, last = random.choice(FIRST), random.choice(LAST)
  students.append({'student_id': sid, 'first_name': first, 'last_name': last,
                   'email': f'{first.lower()}.{sid.lower()}@student.example.edu',
                   'city': random.choice(CITIES), 'year': random.choice([1, 1, 2, 2, 3]),
                   'enrolled_on': (date(2023, 9, 1) + timedelta(days=365 * random.randint(0, 2))).isoformat()})
  ability = random.gauss(70, 12)                           # each student has a typical level
  for course in random.sample(sorted(COURSES), k=random.choice([1, 2, 2, 3])):
    enrollments.append({'student_id': sid, 'course_code': course, 'term': random.choice(['2025-S1', '2025-S2'])})
    day = date(2025, 2, 1) + timedelta(days=random.randint(0, 200))
    for i, topic in enumerate(COURSES[course]):
      if random.random() < 0.85:                           # some topics not assessed yet
        score = max(5, min(100, round(random.gauss(ability - 4 * i, 12))))
        assessments.append({'assessment_id': f'A{len(assessments) + 1:04d}', 'student_id': sid,
                            'topic': topic, 'score': score, 'taken_on': (day + timedelta(days=14 * i)).isoformat()})

OUT.mkdir(parents=True, exist_ok=True)
for name, rows in [('students', students), ('enrollments', enrollments), ('assessments', assessments)]:
  with open(OUT / f'{name}.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
  print(f'{name}.csv: {len(rows)} rows')
