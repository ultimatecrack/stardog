r"""Run the EduGraph production pipeline from the command line, e.g. in CI or a nightly scheduler (Chapter 18).

    ..\.venv\Scripts\python ops\edugraph_pipeline.py run      --env dev
    ..\.venv\Scripts\python ops\edugraph_pipeline.py history  --env dev
    ..\.venv\Scripts\python ops\edugraph_pipeline.py teardown --env dev

`run` exits with code 1 when a quality gate blocks the run, so CI marks the job as failed and the
live graphs stay as they were. Set EDUGRAPH_STARDOG_PASSWORD (letters and digits) to also create
the API's least-privilege user.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from kg import client, pipeline                  # noqa: E402

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('action', choices=['run', 'history', 'teardown'])
  parser.add_argument('--env', default='dev', help='environment name: dev, test, prod, …')
  parser.add_argument('--data', default=str(ROOT / 'data' / 'edugraph'), help='folder with curriculum.ttl, sis/ and lessons/')
  args = parser.parse_args()
  env = pipeline.Environment(args.env)
  with client.connect() as conn:
    if args.action == 'run':
      result = pipeline.Pipeline(conn, env, data_dir=Path(args.data),
                                 api_password=os.environ.get('EDUGRAPH_STARDOG_PASSWORD')).run()
      print(result['status'])
      if result['report'] is not None and not result['report'].ok:
        print(result['report'].results.head(20).to_string())
      sys.exit(0 if result['status'] == 'ok' else 1)
    elif args.action == 'history':
      print(pipeline.history(conn, env).to_string())
    else:
      print(pipeline.teardown(conn, env))
