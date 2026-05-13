"""Runner feature flags (legacy -- Python is always enabled for SECOFS-UFS SCHISM)."""
from __future__ import annotations


def is_python_enabled(step: str) -> bool:
    return True
