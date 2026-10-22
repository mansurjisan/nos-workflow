"""Per-stage input-file manifest for the run stages (nowcast/forecast/post).

The nowcast/forecast/post stages each write a
``{run}.t{cyc}z.{pdy}.inputs.{stage}.json`` file to $COMOUT listing the
input files the stage consumed, grouped by category/source. Filenames
only -- no checksums, sizes, or mtimes.

This is the run-stage counterpart to the prep manifest written by
``nos_utils.orchestrator.PrepOrchestrator._write_inputs_manifest``; the
JSON shape (top-level keys + per-group ``{category, source, count,
files}``) is a cross-repo convention and must stay byte-shape identical
to the prep side.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


class InputCollector:
    """Accumulate consumed input files grouped by ``(category, source)``.

    Mirrors the prep-side capture collector
    (``nos_utils.forcing._log``): :meth:`groups` returns the same
    ``[{category, source, count, files}]`` shape, sorted by
    ``(category, source)``, with files merged in add-order as ``str``
    full paths.
    """

    def __init__(self) -> None:
        self._buckets: Dict[Tuple[str, str], List[str]] = {}

    def add(
        self,
        category: str,
        source: str,
        files: Iterable[PathLike],
    ) -> None:
        """Record ``files`` under the ``(category, source)`` group.

        Files are stored as ``str`` full paths in the order added; repeat
        calls for the same ``(category, source)`` merge into one group.
        """
        bucket = self._buckets.setdefault((category, source), [])
        bucket.extend(str(f) for f in files)

    def groups(self) -> List[dict]:
        """Return grouped entries, sorted by ``(category, source)``.

        Each entry is ``{"category", "source", "count", "files"}`` -- the
        same shape the prep manifest emits. Files keep their add-order.
        """
        return [
            {
                "category": cat,
                "source": src,
                "count": len(files),
                "files": list(files),
            }
            for (cat, src), files in sorted(self._buckets.items())
        ]


def write_inputs_manifest(
    comout: Optional[PathLike],
    run: str,
    cyc: str,
    pdy: str,
    stage: str,
    collector: InputCollector,
    phase: Optional[str] = None,
) -> Optional[Path]:
    """Write the per-stage input manifest to $COMOUT.

    Emits ``{run}.t{cyc}z.{pdy}.inputs.{stage}.json`` (the prep side uses
    the identical ``{prefix}.{cycle}.{pdy}.inputs.{stage}.json`` idiom
    with ``cycle=t{cyc}z``). ``phase`` is the stage name for
    nowcast/forecast and ``None`` for post.

    Returns the manifest path, or ``None`` if it could not be written
    (``comout`` unset or unwritable -- logged as a warning, never raised:
    manifest writing must not fail a stage).
    """
    if comout is None:
        logger.warning("  Skipping input manifest: COMOUT not set")
        return None

    comout = Path(comout)
    cycle = f"t{cyc}z"
    groups = collector.groups()

    manifest = {
        "ofs": run,
        "pdy": pdy,
        "cyc": cyc,
        "stage": stage,
        "phase": phase,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": groups,
    }

    manifest_path = comout / f"{run}.{cycle}.{pdy}.inputs.{stage}.json"
    try:
        with open(manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=2)
        logger.info(
            "  Wrote input manifest -> %s (%d group(s))",
            manifest_path.name, len(groups),
        )
        return manifest_path
    except OSError as exc:
        logger.warning("  Failed to write input manifest: %s", exc)
        return None


__all__ = ["InputCollector", "write_inputs_manifest"]
