import os

import stardog
from dotenv import load_dotenv

load_dotenv()

conn_details = {
  'endpoint': os.environ['STARDOG_ENDPOINT'],
  'username': os.environ['STARDOG_USERNAME'],
  'password': os.environ['STARDOG_PASSWORD'],
}

# Temporary database, dropped at the end (the Stardog Cloud plan limits how many databases exist)
DB_NAME = os.environ['STARDOG_DATABASE']

EXAMPLE_TTL = b"""
@prefix ex:   <http://example.org/> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

# Companies
ex:acme    a ex:Company ; ex:name "Acme Corp" ;    ex:city "Bengaluru" .
ex:globex  a ex:Company ; ex:name "Globex Ltd" ;   ex:city "Pune" .
ex:initech a ex:Company ; ex:name "Initech" ;      ex:city "Hyderabad" .

# People
ex:alice a ex:Person ; ex:name "Alice" ; ex:age "30"^^xsd:integer ; ex:worksFor ex:acme ;
         ex:role "Data Engineer" ; ex:knows ex:bob, ex:carol .
ex:bob   a ex:Person ; ex:name "Bob" ;   ex:age "35"^^xsd:integer ; ex:worksFor ex:acme ;
         ex:role "Manager" ; ex:knows ex:dave .
ex:carol a ex:Person ; ex:name "Carol" ; ex:age "28"^^xsd:integer ; ex:worksFor ex:globex ;
         ex:role "Data Scientist" ; ex:knows ex:alice .
ex:dave  a ex:Person ; ex:name "Dave" ;  ex:age "42"^^xsd:integer ; ex:worksFor ex:initech ;
         ex:role "Architect" .
ex:eve   a ex:Person ; ex:name "Eve" ;   ex:age "25"^^xsd:integer ; ex:worksFor ex:globex ;
         ex:role "Analyst" ; ex:knows ex:carol, ex:dave .

# Projects
ex:graphProject a ex:Project ; ex:name "Knowledge Graph" ; ex:budget "50000"^^xsd:decimal ;
                ex:ownedBy ex:acme ; ex:member ex:alice, ex:bob .
ex:mlProject    a ex:Project ; ex:name "ML Platform" ;     ex:budget "80000"^^xsd:decimal ;
                ex:ownedBy ex:globex ; ex:member ex:carol, ex:eve .
"""

# Who works where, and in which role
QUERY = """
PREFIX ex: <http://example.org/>
SELECT ?person ?role ?company ?city {
  ?p a ex:Person ; ex:name ?person ; ex:role ?role ; ex:worksFor ?c .
  ?c ex:name ?company ; ex:city ?city .
}
ORDER BY ?company ?person
"""

with stardog.Admin(**conn_details) as admin:
  if DB_NAME in [d.name for d in admin.databases()]:
    admin.database(DB_NAME).drop()
  db = admin.new_database(DB_NAME)

  try:
    with stardog.Connection(DB_NAME, **conn_details) as conn:
      conn.begin()
      conn.add(stardog.content.Raw(EXAMPLE_TTL, content_type='text/turtle'))
      conn.commit()
      results = conn.select(QUERY)
      for row in results['results']['bindings']:
        print(row['person']['value'], '|', row['role']['value'], '|',
              row['company']['value'], '|', row['city']['value'])
  finally:
    # db.drop()
    pass
