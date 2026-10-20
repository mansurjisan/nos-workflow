"""SECOFS cards and launchers take the clone location from the launcher. Offline. MJ (10/19/26)"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
STAGES = ("prep", "nowcast", "forecast", "post")
CARDS = [REPO / "pbs" / f"jnos_{s}_00.pbs" for s in STAGES] + [
    REPO / "pbs" / "secofs_ufs_ww3" / f"jnos_{s}_00.pbs" for s in STAGES
]
RETRY_CARDS = [c for c in CARDS if "nowcast" in c.name or "forecast" in c.name]
LAUNCHERS = [
    REPO / "pbs" / "launch_secofs_ufs.sh",
    REPO / "pbs" / "secofs_ufs_ww3" / "launch_secofs_ufs_ww3.sh",
    REPO / "pbs" / "secofs_ufs_ww3" / "launch_secofs_ufs_ww3_warm.sh",
]


def _ids(paths):
    return [str(p.relative_to(REPO)) for p in paths]


@pytest.mark.parametrize("card", CARDS, ids=_ids(CARDS))
def test_card_defaults_not_assigns(card):
    text = card.read_text()
    assert not re.search(r"^(export )?PACKAGEROOT=/", text, re.M)
    assert re.search(r"^PACKAGEROOT=\$\{PACKAGEROOT:-[^}]+\}$", text, re.M)
    assert re.search(r"^HOMEnos=\$\{HOMEnos:-.+\}$", text, re.M)
    assert re.search(r"^export HOMEnos$", text, re.M)
    assert re.search(r"^export PACKAGEROOT=\$\{HOMEnos%/\*\}", text, re.M)   # after the module block, which resets it. MJ (10/19/26)
    assert "${PACKAGEROOT}/nos-workflow/versions" not in text


@pytest.mark.parametrize("card", RETRY_CARDS, ids=_ids(RETRY_CARDS))
def test_retry_qsub_forwards_clone(card):
    qsubs = [l for l in card.read_text().splitlines() if "qsub -v" in l and not l.lstrip().startswith("#")]
    assert qsubs
    for l in qsubs:
        assert "PACKAGEROOT=${PACKAGEROOT}" in l and "HOMEnos=${HOMEnos}" in l


@pytest.mark.parametrize("launcher", LAUNCHERS, ids=_ids(LAUNCHERS))
def test_launcher_derives_pkg_and_forwards(launcher):
    text = launcher.read_text()
    assert re.search(r'^PKG="\$\(cd "\$\{PKG:-\$\(dirname "\$\(readlink -f "\$0"\)"\)/[./]+\}" && pwd\)" \|\|', text, re.M)
    assert "/lfs/h1/nos/estofs/noscrub/${USER}/packages/nos-workflow" not in text
    code = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    qsubs = [l for l in code if "qsub -v" in l]
    assert qsubs
    for l in qsubs:
        assert 'PACKAGEROOT=$(dirname "$PKG")' in l or '${vars}' in l
    if "local vars=" in text:
        assert 'PACKAGEROOT=$(dirname "$PKG"),HOMEnos=${PKG}' in text
    else:
        assert all('HOMEnos=$PKG' in l for l in qsubs)


def test_dryrun_qsub_carries_clone_path(tmp_path):
    clone = tmp_path / "pk" / "nos-workflow"
    shutil.copytree(REPO / "pbs", clone / "pbs", ignore=shutil.ignore_patterns("__pycache__"))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "qsub").write_text("#!/bin/sh\necho 1.fake\n")
    (bindir / "qsub").chmod((bindir / "qsub").stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "DRYRUN": "1",
           "RPTDIR": str(tmp_path / "rpt"), "PDY": "20261019", "STAGES": "prep"}
    env.pop("PKG", None)
    r = subprocess.run(["bash", str(clone / "pbs" / "launch_secofs_ufs.sh"), "00"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"PACKAGEROOT={tmp_path / 'pk'},HOMEnos={clone}" in r.stdout
