"""Runner feature flags (legacy -- Python is always enabled for the SCHISM-UFS runner)."""
from __future__ import annotations


def is_python_enabled(step: str) -> bool:
    return True
