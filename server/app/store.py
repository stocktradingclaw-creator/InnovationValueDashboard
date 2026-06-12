"""In-memory data store for the MVP. Swap for a database when persistence matters."""
import itertools
from typing import Any, Dict, List

# source_type -> list of row dicts
datasets: Dict[str, List[Dict[str, Any]]] = {}

# submitted business cases with their generated ROI plans
business_cases: List[Dict[str, Any]] = []

_counter = itertools.count(1)


def next_id(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def reset() -> None:
    datasets.clear()
    business_cases.clear()
