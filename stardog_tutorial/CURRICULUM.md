# Stardog with Python: Curriculum (Basic → Expert)

18 chapters in 4 levels. Each chapter is one Jupyter notebook in `notebooks/`, with reusable code in `src/kg/` and SPARQL in `.rq` files. Each level ends with a mini-project.

**Status:** outline only. No notebooks written yet.

---

## 1. What your Stardog Cloud endpoint supports

Checked on 2026-09-27 against `sd-fd55b7e2.stardog.cloud`, using read-only calls only. Nothing was created or enabled.

| | |
|---|---|
| Stardog version | **12.1.4** |
| Memory | 1 GB heap + 1 GB native, so keep datasets small (up to ~1M triples) |
| Databases | `mysampledb`, plus the system `catalog` and `querylog`. Creating a second user database **worked** on 2026-09-27 (Ch 2), although an earlier attempt in this project hit a `403` quota. |
| Reasoning | SL (the default profile) |
| pystardog | 0.21.0, with the `stardog.cloud` Voicebox module available |

| Feature | Status | Evidence / note | Chapters |
|---|---|---|---|
| Admin API: list DBs, users, roles, stored queries | ✅ Works | Listed 3 users, 3 roles, 1 stored query | 2, 14 |
| Create / drop databases | ✅ Works | Created and dropped `tutorial_ch02_tmp`. Plans can limit the count (`403`), so chapters isolate work with named graphs | 2, 14 |
| Load data, transactions, rollback | ✅ Works | Verified in `quick_start` tutorial | 3, 5 |
| SPARQL SELECT / ASK / CONSTRUCT / UPDATE | ✅ Works | Verified | 4, 5, 6 |
| Parameterized queries (`bindings=`) | ✅ Works | `select(..., bindings={'s': '<iri>'})` returned the right row | 6 |
| PATHS queries | ✅ Works | 5 paths S3 → R4 in supply chain | 6 |
| Query plans (`explain`) | ✅ Works | Verified | 15 |
| Reasoning with named schemas | ✅ Works | Verified in `recipes/` and `supply_chain/` | 7, 8 |
| Stardog Rules | ❓ Untested | Part of the SL reasoner, so expected to work | 8 |
| SHACL validation (`conn.icv()`) | ✅ Works | `is_valid()` returned a result | 9 |
| Virtual graphs / data sources API | ✅ API available | Lists are empty. **Stardog Cloud cannot reach a database on `localhost`.** It needs a publicly reachable DB, a CSV import, or local Docker | 10 |
| BITES document store (`conn.docs()`) | ❌ Not available | `404 Not Found` on this endpoint | 11 |
| Full-text search (`textMatch`) | ⚠️ Disabled | `search.enabled = false`. Enabling may need the DB taken offline; to be tested in Ch 12 | 12 |
| Geospatial (GeoSPARQL) | ⚠️ Disabled | `spatial.enabled = false`, same as above | 12 |
| Similarity search (`spa:` models) | ❓ Untested | Query syntax accepted; needs a model to be trained (a write) | 12 |
| GraphQL | ✅ Works | Endpoint responds (no schemas defined yet) | 13 |
| Users / roles / permissions | ✅ Likely | Your user has `CREATE`/`GRANT` on `*`; not tested | 14 |
| Named-graph security | ⚠️ Disabled | `security.named.graphs = false` | 14 |
| Backup / restore | ❓ Untested | Usually managed by Stardog Cloud | 14 |
| Cluster | ❌ Not available | `404`, single node | 18 |
| Graph algorithms (Spark connector) | ✅ Works | Verified in `supply_chain/` (runs locally, reads/writes Cloud) | extra chapter, see §3 |
| Voicebox | ❓ Needs token | Needs a Voicebox **app API token** from Stardog Cloud | 16 |

**Local Docker as a fallback.** For ❌ and some ⚠️ features, run Stardog in Docker; Docker is installed on this machine. It needs a free Stardog license key. Chapters that need it say so, and always offer a Cloud path where one exists.

---

## 2. Datasets

Different datasets for different skills. Each is introduced once and then reused.

| Dataset | Shape | Why | Used in |
|---|---|---|---|
| **Recipes & Nutrition** | Recipes, ingredients, ingredient categories (Parmesan → Cheese → Dairy), allergens, diets, nutrients. Extends the existing `recipes/data` CSVs | Intuitive; has hierarchies (property paths), rules (allergens, diets), constraints (SHACL), similarity | Ch 3-9, 12, 16 |
| **EduGraph** | Topics with prerequisites, courses, students, assessments, lesson documents | Deep prerequisite chains, per-student data (security, APIs), text documents (NLP), a natural agent use case | Ch 10, 11, 13, 14, 17, 18 |
| **Supply Chain** | Facilities, routes, plus lat/long for geo | Graph algorithms and geospatial | Ch 12 (geo), extra analytics chapter |
| **Synthetic scale data** | Generated EduGraph with ~500k triples (fits in 1 GB) | Slow queries need volume | Ch 15 |
| **Company / people** (Ch 1-2 only) | 5 people, 3 companies | Smallest possible first contact | Ch 1, 2 |

---

## 3. Suggested changes to the original outline

1. **Add a graph analytics chapter** (PageRank, components, communities, triangles). It's missing from the outline, and `supply_chain/supply_chain_tutorial.ipynb` already covers it. Suggest **Ch 15b** in Level 4, or move it in as Ch 12b.
2. **Ch 2 "create / drop a database":** teach it with a guard (`if slot free`), and make **named graphs** the standard way to isolate work. That's what the existing tutorials already do.
3. **Ch 10 Virtual Graphs:** the Cloud path uses a **CSV import** plus a cloud-hosted Postgres (such as a free Neon or Supabase instance). The Docker path uses local Postgres with local Stardog.
4. **Ch 11:** BITES isn't available, so the **custom NLP / LLM extraction** path is primary. BITES is optional, Docker only.
5. **Ch 14:** backup/restore and clustering are conceptual on Cloud, with hands-on via Docker.
6. **LLM choice (Ch 11, 16, 17):** Claude API (best quality) or Ollama (already installed, local and free). To decide before Level 3.

---

## 4. Chapters

Time = estimated learner time including hands-on. ☁️ = works on your Cloud endpoint, 🐳 = needs local Docker for part of it.

### Level 1: Foundations (Beginner), ~8 h

| Ch | Title | Learning objectives | Dataset | Hands-on | Time | Env |
|---|---|---|---|---|---|---|
| 1 | Why knowledge graphs? | Explain triples vs property graphs; open vs closed world; IRIs and namespaces; the Stardog product stack | Company / people | Sign in to Cloud, open Studio, run a first query; optional Docker setup | 1.5 h | ☁️ 🐳 |
| 2 | Connecting from Python | Use `Admin` vs `Connection`; keep credentials in `.env`; manage lifecycles with `with`; diagnose `401` / `403` / `404` / `400` | Company / people | List DBs, options, users and permissions; create/drop a DB (guarded); the `kg.client` module and `check_setup.py` | 1.5 h | ☁️ |
| 3 | RDF data and loading | Read and write Turtle, N-Triples, JSON-LD, TriG; literals, datatypes, language tags, blank nodes; named vs default graph; load files in a transaction | Recipes | Convert the recipe CSVs to Turtle; load them into `urn:tutorial:recipes`; export as JSON-LD | 2 h | ☁️ |
| 4 | SPARQL essentials | SELECT, FILTER, OPTIONAL, UNION, ORDER BY, LIMIT; `select` / `ask` / `graph`; results → DataFrame | Recipes | `run_query(name) -> DataFrame` loading `.rq` files from `src/kg/queries/` | 3 h | ☁️ |

**Mini-project 1:** *Recipe explorer.* A notebook that answers 10 questions ("recipes under 30 min without dairy", …) using only `.rq` files and the helper.

### Level 2: Modeling & Querying (Intermediate), ~13 h

| Ch | Title | Learning objectives | Dataset | Hands-on | Time | Env |
|---|---|---|---|---|---|---|
| 5 | Updates and transactions | INSERT DATA, DELETE/INSERT WHERE; transaction semantics and rollback; batching large loads | Recipes | Idempotent `upsert_recipe()`; batch-load 10k generated ratings in chunks | 2 h | ☁️ |
| 6 | Advanced SPARQL | GROUP BY/HAVING, subqueries, BIND, VALUES; property paths `+ * / ^`; GRAPH/FROM; `bindings=` instead of string formatting (injection demo); PATHS queries | Recipes | "All ancestor categories of an ingredient, at any depth"; safe parameterized search | 3 h | ☁️ |
| 7 | Ontology design (RDFS / OWL) | Classes, subclasses, object vs datatype properties, domain/range; equivalentClass, inverseOf, TransitiveProperty, someValuesFrom, disjointness; OWL profiles; schema in its own named graph | Recipes | Write `ontology/recipes.ttl`; load it as named schema `RecipeKG`; view it in Studio/Explorer | 3 h | ☁️ |
| 8 | Reasoning | Reasoning per query; with vs without comparison; property chains; Stardog Rules; explaining inferences; performance cost | Recipes | Rules: "recipe contains allergen", "VeganRecipe", "HighProteinRecipe"; print explanations with `explain_inference` | 2.5 h | ☁️ |
| 9 | Data quality with SHACL | Shapes, cardinality, datatype and pattern constraints, severities; validation reports from Python | Recipes | A validation gate: reject a CSV batch that breaks the shapes, with a readable report | 2.5 h | ☁️ |

**Mini-project 2:** *Allergen-safe menu service.* Load, validate and reason, then answer "safe recipes for a guest allergic to X and on diet Y".

### Level 3: Integration & Engineering (Advanced), ~16 h

| Ch | Title | Learning objectives | Dataset | Hands-on | Time | Env |
|---|---|---|---|---|---|---|
| 10 | Virtual Graphs | SMS2 and R2RML; data sources; virtualize vs materialize; query pushdown | EduGraph | Map a `students` table and query it with the curriculum graph in one query. CSV import on Cloud, live Postgres on Docker | 3 h | ☁️ 🐳 |
| 11 | Unstructured data and entity linking | Entity extraction and linking; writing extracted triples with provenance; BITES overview | EduGraph | Extract topics from lesson PDFs with an LLM or spaCy; link them to topic nodes; store the source per triple | 3 h | ☁️ (🐳 BITES) |
| 12 | Search, similarity and geospatial | `textMatch`; similarity models; GeoSPARQL | Recipes + Supply Chain | "Recipes similar to X"; keyword search; "facilities within 500 km of Rotterdam" | 3 h | ⚠️ ☁️ (enable) / 🐳 |
| 13 | GraphQL and building APIs | Stardog GraphQL and schema mapping; stored queries; a FastAPI service | EduGraph | `GET /students/{id}/gaps` backed by stored SPARQL, plus a GraphQL query of the same data | 3 h | ☁️ |
| 14 | Administration and DevOps | Users, roles, permissions, named-graph security; DB options; backup/restore; stored queries and functions; CI/CD; pytest fixtures | EduGraph | Teacher vs student roles; a deploy script; pytest with a temp **named graph** per test (temp DB on Docker) | 4 h | ☁️ 🐳 |

**Mini-project 3:** *EduGraph API.* A FastAPI app with auth-aware endpoints, tests and a deploy script.

### Level 4: Expert (Performance, AI and Architecture), ~20 h

| Ch | Title | Learning objectives | Dataset | Hands-on | Time | Env |
|---|---|---|---|---|---|---|
| 15 | Query performance | Read `explain` plans, cardinalities, join order, statistics; selective patterns first; bounded paths; reasoning scope | Synthetic EduGraph (~500k triples) | Profile 3 slow queries, rewrite them, and benchmark before/after in Python | 3 h | ☁️ |
| 15b | *(new)* Graph analytics | PageRank, (strongly) connected components, label propagation, triangle count; the Spark connector; what-if graphs | Supply Chain | Existing `supply_chain_tutorial.ipynb`, moved and adapted | 2.5 h | ☁️ (+ local Java) |
| 16 | Knowledge graphs and LLMs (GraphRAG) | Voicebox via pystardog; text-to-SPARQL grounded in the ontology, with validation and a retry loop; hybrid retrieval (vector → graph expansion → reasoning → LLM) | Recipes | A LangChain/LangGraph tool node that calls stored queries; compare Voicebox with a custom pipeline | 4 h | ☁️ |
| 17 | Agentic architectures | KG as agent memory and guardrail (SHACL before acting); Stardog over MCP; provenance with named graphs and PROV-O | EduGraph | A multi-agent tutor recommending learning paths, with every action validated and audited | 4 h | ☁️ |
| 18 | Production architecture and capstone | Clustering and caching; hybrid virtual/materialized; ontology versioning and governance; multi-tenancy | EduGraph | **Capstone:** ingestion (VG + docs) → SHACL → reasoning → FastAPI → GraphRAG chat → monitoring dashboard | 6+ h | ☁️ 🐳 |

**Total:** about 60 hours of learner time.

---

## 5. Conventions for every chapter

- **Isolation:** each chapter writes only to its own named graphs (`urn:tutorial:chNN:*`) and cleans up. Never `clear()` without `graph_uri`.
- **SPARQL in `.rq` files** under `src/kg/queries/`, loaded by name.
- **Neo4j box:** a one-line Cypher equivalent for each key idea.
- **Runnable end to end:** each notebook is executed against the Cloud endpoint before it's committed, so outputs are real.
- **Structure of a notebook:** objectives → concepts → hands-on → exercises (with hidden solutions) → summary / cheat sheet.

## 6. Planned folder structure

```
stardog_tutorial/
├── CURRICULUM.md          this file
├── 00_setup/              .env.example, docker-compose.yml (Stardog + Postgres), setup checks
├── data/
│   ├── company/  recipes/  edugraph/  supply_chain/
│   └── generators/        scripts for synthetic data
├── ontology/              recipes.ttl, edugraph.ttl, rules/*.sms, shapes/*.ttl, mappings/*.sms
├── notebooks/             ch01_why_knowledge_graphs.ipynb … ch18_capstone.ipynb
├── src/kg/
│   ├── client.py          connection helpers
│   ├── queries/           *.rq files + run_query()
│   ├── loaders/  validators/
├── api/                   FastAPI app (Ch 13+)
└── tests/                 pytest fixtures (temp named graph per test)
```

## 7. Decisions

| # | Decision | Consequence |
|---|---|---|
| 1 | Graph analytics is **Ch 15b** | Adapted from `supply_chain/supply_chain_tutorial.ipynb` |
| 2 | LLM: **Ollama** (local) | Ch 11, 16, 17 use Ollama models; no API keys needed |
| 3 | **No local Docker Stardog** (no license) | Every chapter runs on Stardog Cloud only. 🐳 parts become explanations and Cloud alternatives: Ch 10 uses CSV import / cloud-hosted Postgres; Ch 11 skips BITES; Ch 12 depends on enabling search/geo in Cloud; Ch 14 backup/cluster are conceptual; tests use temp named graphs |
| 4 | `quick_start/` and `supply_chain/` **stay separate**, at the same level as `stardog_tutorial/` | The tutorial is self-contained |

## 8. Progress

| Ch | Status |
|---|---|
| 1 | ✅ Written and run against Stardog Cloud |
| 2 | ✅ Written and run against Stardog Cloud |
| 3 | ✅ Written and run against Stardog Cloud |
| 4 | ✅ Written and run against Stardog Cloud (includes Mini-project 1) |
| 5 | ✅ Written and run against Stardog Cloud |
| 6 | ✅ Written and run against Stardog Cloud |
| 7 | ✅ Written and run against Stardog Cloud |
| 8 | ✅ Written and run against Stardog Cloud |
| 9 | ✅ Written and run against Stardog Cloud (includes Mini-project 2) |
| 10 | ✅ Written and run against Stardog Cloud (CSV imports; live virtual graph runs only with your own DB in `.env`) |
| 11 | ✅ Written and run (Stardog Cloud + local Ollama: qwen2.5:7b, nomic-embed-text) |
| 12 | ✅ Written and run (switches `search.enabled` / `spatial.enabled` on briefly, restores them at the end) |
| 13 | ✅ Written and run against Stardog Cloud (API tested in-process and over HTTP) |
| 14 | ✅ Written and run against Stardog Cloud (includes Mini-project 3; creates and removes tutorial users/roles) |
| 15 | ✅ Written and run against Stardog Cloud (loads ~610k generated triples temporarily; lowers `query.timeout` briefly and restores it) |
| 15b | ✅ Written and run (Spark connector runs locally with the portable Java 11 in `tools/`) |
| 16 | ✅ Written and run (local Ollama; no Voicebox token, so the Voicebox cell is skipped) |
| 17 | ✅ Written and run (local Ollama qwen2.5:7b; agent conversations cached in `data/edugraph/agent_llm_cache.json`; evaluation: 3/5 plans saved by the basic agent, 4/5 with `order_topics` + orchestrator, no invalid plan ever written) |
| 18 | ✅ Written and run (capstone pipeline, API with pool/cache/`/ask`/`/metrics`, two tenants, dashboard; no cluster on Cloud (`404`), so clustering and cache targets are explained, not run) |
