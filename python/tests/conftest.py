import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
FIXTURES = ROOT / "tests" / "fixtures"


def fixture(name):
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)
