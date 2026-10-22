"""Per-cycle outputs manifest for the post stage.

Companion to ``nos_workflow.inputs_manifest``: post writes
``{run}.t{cyc}z.{pdy}.outputs.post.json`` to $COMOUT recording every
product that ran, its status, and the COMOUT files it created. Same
ground rules as the inputs side -- full file paths with no metadata
(no checksums, sizes, or mtimes), best-effort, never fails the stage.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

from .base import ProductResult

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def write_outputs_manifest(
    comout: Optional[PathLike],
    run: str,
    cyc: str,
    pdy: str,
    results: Iterable[ProductResult],
    stage: str = "post",
) -> Optional[Path]:
    """Write the product-outcome manifest; return its path or None."""
    if comout is None:
        logger.warning("  Skipping outputs manifest: COMOUT not set")
        return None

    products = [
        {
            "name": r.name,
            "status": r.status,
            "count": len(r.outputs),
            "outputs": list(r.outputs),
            "detail": r.detail,
            "duration_s": round(r.duration_s, 3),
        }
        for r in results
    ]

    manifest = {
        "ofs": run,
        "pdy": pdy,
        "cyc": cyc,
        "stage": stage,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "products": products,
    }

    manifest_path = Path(comout) / f"{run}.t{cyc}z.{pdy}.outputs.{stage}.json"
    try:
        with open(manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=2)
        logger.info(
            "  Wrote outputs manifest -> %s (%d product(s))",
            manifest_path.name, len(products),
        )
        return manifest_path
    except OSError as exc:
        logger.warning("  Failed to write outputs manifest: %s", exc)
        return None


__all__ = ["write_outputs_manifest"]
