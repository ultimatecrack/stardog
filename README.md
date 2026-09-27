# Stardog Learning Projects

Python scripts for learning Stardog Cloud: connecting, building a model, and running graph algorithms.

```
quick_start/                 Connect to Stardog, load a small people/companies dataset, run a query
  quick_start_tutorial.ipynb   step-by-step tutorial: loading, SPARQL, updates, transactions
  quick_start.py
recipes/                     Recipe / ingredient / allergen model; allergens inferred by reasoning
  create_model.py
  data/*.csv
supply_chain/                Logistics supply chain use case solved with Stardog's graph algorithms
  supply_chain_tutorial.ipynb  step-by-step tutorial: all 5 algorithms, charts, what-if analysis
  load_data.py, run_analytics.py, report.py
  data/*.csv
tools/                       Spark connector, Java 11, Hadoop winutils (used by supply_chain)
stardog_training_material/   Training slides and exercises
.env                         Stardog credentials (shared by all folders)
```

## Setup

Nothing needs to be installed on Windows. Everything lives in this folder:

| Item | Location | Used by |
|---|---|---|
| Python packages (`pystardog`, `python-dotenv`, `rdflib`) | `.venv/` | all scripts |
| Notebook packages (`ipykernel`, `pandas`, `matplotlib`, `networkx`) | `.venv/` | the tutorials |
| Stardog Spark connector (bundles Spark 3.5) | `tools/stardog-spark-connector-3.3.0.jar` | `supply_chain/run_analytics.py` |
| Portable Java 11 | `tools/jdk-11.0.32.1+1-jre/` | `supply_chain/run_analytics.py` |
| Hadoop `winutils.exe` / `hadoop.dll` (Spark on Windows) | `tools/hadoop/bin/` | `supply_chain/run_analytics.py` |

Your system Java 17 is **not** used: the connector's bundled Scala 2.12.12 crashes on Java 17.

### Credentials

Create a `.env` file in this folder:

```
STARDOG_ENDPOINT=https://<your-endpoint>.stardog.cloud:5820
STARDOG_USERNAME=<server user>
STARDOG_PASSWORD=<password>
STARDOG_DATABASE=mysampledb
```

`STARDOG_USERNAME` must be a user created **on the Stardog server** (Studio > Security > Users), not your cloud.stardog.com login. The cloud login returns `401 Unauthorized`.

`.env` holds your password: never commit or share it.

### Setting up on a new machine

1. Install Python 3.11+ and create the venv:
   ```
   python -m venv .venv
   .venv\Scripts\pip install pystardog python-dotenv rdflib ipykernel pandas matplotlib networkx
   ```
2. Download into `tools/` (only needed for the supply chain algorithms):
   - Connector: https://stardog-spark.s3.amazonaws.com/stardog-spark-connector-3.3.0.jar
   - Java 11 JRE (unzip into `tools/`): https://api.adoptium.net/v3/binary/latest/11/ga/windows/x64/jre/hotspot/normal/eclipse
   - `winutils.exe` and `hadoop.dll` into `tools/hadoop/bin/`: https://github.com/cdarlint/winutils/tree/master/hadoop-3.3.5/bin

## Tutorials

The best place to start. Open a notebook in VS Code and select the `.venv` kernel (*Select Kernel → Python Environments → .venv*):

| Notebook | Covers |
|---|---|
| [quick_start/quick_start_tutorial.ipynb](quick_start/quick_start_tutorial.ipynb) | Connecting, named graphs, loading data, SELECT / ASK / CONSTRUCT, aggregation, property paths, SPARQL Update, rollback, query plans, export |
| [supply_chain/supply_chain_tutorial.ipynb](supply_chain/supply_chain_tutorial.ipynb) | Modelling, reasoning, how the Spark connector works, each graph algorithm explained, run, charted and interpreted, a combined risk table, what-if analysis |

Both are safe to rerun: they only write to their own named graphs (`urn:QuickStart:data`, `urn:SupplyChain:*`). The quick start notebook removes its data at the end, and the supply chain notebook keeps the algorithm results for Studio and Explorer.

## Running the scripts

Run from this (root) folder with the venv's Python:

```
.venv\Scripts\python quick_start\quick_start.py
.venv\Scripts\python recipes\create_model.py
```

## Supply chain use case

A global electronics supply chain (30 facilities, 43 routes) plus a separate South American coffee chain. Suppliers in Asia feed factories, which ship through ports to distribution centers and stores in Europe and the US. Returned goods go from US stores via a returns center back to the Pune factory.

Each algorithm answers one business question:

| Algorithm | Question | Result property |
|---|---|---|
| PageRank | Which facilities are the most critical? | `sc:pageRank` |
| Connected Components | Which networks are fully separate? | `sc:component` |
| Strongly Connected Components | Where are the closed loops (returns, refurbishment)? | `sc:stronglyConnectedComponent` |
| Label Propagation | Which facilities form natural logistics clusters? | `sc:community` |
| Triangle Count | Which facilities have a backup route? | `sc:triangleCount` |

### Run it

```
.venv\Scripts\python supply_chain\load_data.py
.venv\Scripts\python supply_chain\run_analytics.py
.venv\Scripts\python supply_chain\report.py
```

1. **`load_data.py`**: loads `supply_chain/data/*.csv` into Stardog and registers the **SupplyChain** model (selectable in Explorer).
2. **`run_analytics.py`**: runs the 5 algorithms as Spark jobs (about 15-25 s each). To run only some, name them, e.g. `run_analytics.py PageRank TriangleCount`.
3. **`report.py`**: reads the results back and prints the findings.

### Key finding

Pune Assembly Plant (F2) and Port of Mumbai (P3) have the highest PageRank **and** a triangle count of 0. They are the most important facilities and have no backup route, so they are the biggest risk in the network.

### Where the data lives in Stardog

All in the `STARDOG_DATABASE` database, each in its own named graph:

| Named graph | Contents |
|---|---|
| `urn:SupplyChain:SupplyChain` | Model (classes and properties) |
| `urn:SupplyChain:data` | Facilities and routes |
| `urn:SupplyChain:analytics:<Algorithm>` | One result per facility, for each algorithm |

In Studio or Explorer, add `FROM <tag:stardog:api:context:all>` to a query to search all named graphs.

## Notes

- **Stardog Cloud database limit.** The plan allows only a limited number of databases, so the scripts reuse `STARDOG_DATABASE` rather than creating new ones.
- **Scripts are safe to rerun.** Each script clears and reloads only its own named graphs.
- **Warning: `quick_start/quick_start.py` deletes and recreates the `STARDOG_DATABASE` database** before loading its data. Running it wipes everything else in that database: the recipe and supply chain graphs, and models published from Designer such as `Recipe_Basic`.
