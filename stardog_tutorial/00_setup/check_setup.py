"""Check that the tutorial can reach Stardog: python stardog_tutorial/00_setup/check_setup.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kg import client  # noqa: E402

results = client.check_setup()
for check, passed, detail in results:
  print(f"{'PASS' if passed else 'FAIL'}  {check:32} {detail}")
sys.exit(0 if all(passed for _, passed, _ in results) and len(results) == 5 else 1)
