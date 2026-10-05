"""adcprep with a cached mesh decomposition.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/adcirc_baroclinic_2d), adcircmodel.py _maybe_extract_decomposition and
_run_adcprep. The first prep runs ``--partmesh`` then ``--prepall`` and stores
the PE directories in ``$COMGES/<RUN>_<ncpu>.tar``; every later run extracts
that tarball and runs only ``adcprep --prep15``. The archive is keyed on the
rank count and on the mesh and attribute file sizes.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Callable, List, Optional, Sequence

log = logging.getLogger(__name__)

PE_FILES = ("fort.14", "fort.18", "fort.13", "fort.24", "fort.rotm")
CommandRunner = Callable[[Sequence[str], Path], int]


def default_runner(cmd: Sequence[str], cwd: Path) -> int:
    return subprocess.run(list(cmd), cwd=str(cwd), shell=False, check=False).returncode


def archive_path(comges: Path, run: str, ncpu: int) -> Path:
    return Path(comges) / f"{run}_{ncpu}.tar"


def _meta_path(archive: Path) -> Path:
    return archive.with_name(archive.name + ".json")


def _meta(ncpu: int, run_dir: Path) -> dict:
    return {
        "ncpu": ncpu,
        "fort14_size": (run_dir / "fort.14").resolve().stat().st_size,
        "fort13_size": (run_dir / "fort.13").resolve().stat().st_size,
    }


def pe_dirs(run_dir: Path) -> List[Path]:
    return sorted(Path(run_dir).glob("PE[0-9]*"))


def extract_decomposition(archive: Path, run_dir: Path, ncpu: int) -> bool:
    """Extract a matching cached decomposition into ``run_dir``; False when unusable."""
    archive = Path(archive)
    if not archive.is_file() or not _meta_path(archive).is_file():
        return False
    try:
        want = json.loads(_meta_path(archive).read_text())
    except ValueError:
        return False
    if want != _meta(ncpu, run_dir):
        log.warning("decomposition %s does not match this mesh/ncpu; rebuilding", archive)
        return False
    root = Path(run_dir).resolve()
    with tarfile.open(archive, "r:*") as tf:
        for m in tf.getmembers():
            if not str((root / m.name).resolve()).startswith(str(root) + os.sep):
                raise RuntimeError(f"unsafe path in {archive}: {m.name}")
        tf.extractall(run_dir)  # members were checked above
    n = len(pe_dirs(run_dir))
    if n != ncpu:
        raise RuntimeError(
            f"decomposition {archive} has {n} PE directories but ncpu is {ncpu}")
    return True


def store_decomposition(archive: Path, run_dir: Path, ncpu: int) -> None:
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = archive.with_name(archive.name + ".tmp")
    with tarfile.open(tmp, "w") as tf:
        part = Path(run_dir) / "partmesh.txt"
        if part.is_file():
            tf.add(part, arcname="partmesh.txt")
        for pe in pe_dirs(run_dir):
            for name in PE_FILES:
                f = pe / name
                if f.is_file():
                    tf.add(f, arcname=f"{pe.name}/{name}")
    os.replace(tmp, archive)
    _meta_path(archive).write_text(json.dumps(_meta(ncpu, run_dir)) + "\n")


def run_adcprep(adcprep: str, run_dir: Path, ncpu: int, archive: Optional[Path] = None,
                runner: CommandRunner = default_runner) -> str:
    """Decompose the run directory; returns ``"prep15"`` (cache hit) or ``"full"``."""
    run_dir = Path(run_dir)
    if archive is not None and extract_decomposition(archive, run_dir, ncpu):
        steps, mode = ["--prep15"], "prep15"
    else:
        steps, mode = ["--partmesh", "--prepall"], "full"
    for flag in steps:
        rc = runner([adcprep, flag, "--np", str(ncpu)], run_dir)
        if rc != 0:
            raise RuntimeError(f"adcprep {flag} failed with return code {rc}")
    if mode == "full" and archive is not None:
        store_decomposition(archive, run_dir, ncpu)
    return mode
