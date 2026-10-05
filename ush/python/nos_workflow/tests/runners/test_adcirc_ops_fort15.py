"""Golden test: the Python ops fort.15 render against the ops bc/sed commands run in bash. MJ (10/05/26)"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.runners.adcirc import ops as op  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "adcirc" / "ops"
NOW = "2026100512"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("sed") and shutil.which("bc")),
    reason="bash, sed and bc are needed for the golden comparison")

FACTORS = [("K1", 1.0123, 93.17), ("O1", 0.9876, 281.4), ("P1", 1.0004, 12.5), ("Q1", 0.9731, 355.25),
           ("M2", 1.0021, 61.88), ("S2", 1.0, 0.0), ("N2", 1.0021, 7.07), ("K2", 1.2845, 301.9)]

# Verbatim from exstofs_2d_glo_*.sh (bc arithmetic and the nod_equi read). MJ (10/05/26)
READ_NOD = '''
  exec 5<&0 < ${RUN}_nod_equi
      read hh dd mm yyyy
      mm=$(printf "%02d" $mm)
      dd=$(printf "%02d" $dd)
      hh=$(printf "%02d" $hh)
      read con1 fft1 facet1
      read con2 fft2 facet2
      read con3 fft3 facet3
      read con4 fft4 facet4
      read con5 fft5 facet5
      read con6 fft6 facet6
      read con7 fft7 facet7
      read con8 fft8 facet8
'''
SED_TAIL = '''      -e "s/fft1/$fft1/g" -e "s/facet1/$facet1/g" \\
      -e "s/fft2/$fft2/g" -e "s/facet2/$facet2/g" \\
      -e "s/fft3/$fft3/g" -e "s/facet3/$facet3/g" \\
      -e "s/fft4/$fft4/g" -e "s/facet4/$facet4/g" \\
      -e "s/fft5/$fft5/g" -e "s/facet5/$facet5/g" \\
      -e "s/fft6/$fft6/g" -e "s/facet6/$facet6/g" \\
      -e "s/fft7/$fft7/g" -e "s/facet7/$facet7/g" \\
      -e "s/fft8/$fft8/g" -e "s/facet8/$facet8/g" \\
      -e "s/nout/$nout/g" \\
      -e "s/touts/$touts/g" -e "s/toutf/$toutf/g" \\
      -e "s/nhstar/$nhstar/g" -e "s/nhsinc/$nhsinc/g" \\
      -e "s/hh/$hh/g" -e "s/dd/$dd/g" \\
      -e "s/mm/$mm/g" -e "s/yyyy/$yyyy/g" \\
                ${RUN}_fort.15 | \\
  sed -n "/DUMMY/!p" > fort.15
'''
SED_TIDE = '''  sed -e "s/cycle/$time_now/g" \\
      -e "s/ihot/$ihot/g" \\
      -e "s/rnday/$RNDAY/g" \\
''' + SED_TAIL
SED_SURF = '''  sed -e "s/cycle/$time_now/g" \\
      -e "s/ihot/$ihot/g" \\
      -e "s/winc/$winc/g" \\
      -e "s/rnday/$RNDAY/g" \\
''' + SED_TAIL
SED_ADCPREP = '''  sed -e "s/cycle/$time_spi/g" \\
      -e "s/ihot/$ihot/g" \\
      -e "s/rnday/$rnday/g" \\
      -e "s/dramp/$dramp/g" \\
''' + SED_TAIL

SPINUP = '''
spinh=162; ihot=0
rnday=$(echo "scale=5; $spinh/24" | bc)
nout=-3; touts=0.00000; toutf=$rnday; nhstar=3; nhsinc=1800
RNDAY=$rnday
'''
NCST = '''
wndh=3; nowh=6; lsth=180
if [ `expr $(echo "scale=0; $time_hotstart/($wndh*3600)" | bc) % 2` = 0 ]; then ihot=368; else ihot=367; fi
ncstd=$(echo "scale=5; ($time_hotstart+$ncsth*3600)/86400" | bc)
rnday=$(echo "scale=5; $ncstd+$lsth/24" | bc)
winc=3600
nout=-3
touts=$(echo "scale=5; $rnday-($nowh+$lsth)/24" | bc)
toutf=$rnday
nhstar=3
nhsinc=1800
time_ncst=$(echo "scale=0; $ncstd*86400" | bc)
time_hotstart=$(printf "%.0f" "$time_ncst")
RNDAY=$ncstd
'''
FCST = '''
if [ `expr $(echo "scale=0; $time_hotstart/($nowh*3600)" | bc) %% 2` = 0 ]; then ihot=368; else ihot=367; fi
fcstd=$(echo "scale=5; ($time_hotstart)/86400" | bc)
rnday_hotstart=$(echo "scale=5; $fcstd+$lsth/%(div)s" | bc)
nout=3
nhstar=3
nhsinc=%(nhsinc)s
winc=%(winc)s
time_fcst=$(echo "scale=%(sc)s; $rnday_hotstart*86400" | bc)
time_hotstart=$(printf "%%.0f" "$time_fcst")
RNDAY=$rnday_hotstart
'''


def _bash(stream, segment, time_hot, ncsth):
    sed = SED_TIDE if stream == "tide" else SED_SURF
    body = NCST
    if segment in ("fcst1", "fcst2"):
        body += FCST % {"div": 36, "nhsinc": 3600, "winc": 3600, "sc": 0 if stream == "tide" else 5}
    if segment == "fcst2":
        body += FCST % {"div": 72, "nhsinc": 7200, "winc": 10800, "sc": 0 if stream == "tide" else 5}
    template = DATA / f"stofs_2d_glo_{stream}.15"
    script = ("set -e\nRUN=stofs_2d_glo\ntime_now=%s\ntime_hotstart=%s\nncsth=%s\n" % (NOW, time_hot, ncsth)
              + body + "cp %s ${RUN}_fort.15\n" % template + READ_NOD + sed)
    return script


def _run(tmp_path, script):
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(tmp_path.parent / "stofs_2d_glo_nod_equi"), str(tmp_path))
    (tmp_path / "run.sh").write_text(script)
    r = subprocess.run(["bash", "run.sh"], cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return (tmp_path / "fort.15").read_bytes()


def _nod(tmp_path):
    rows = "".join(" %-4s  %7.5f    %7.2f\n" % f for f in FACTORS)
    (tmp_path / "stofs_2d_glo_nod_equi").write_text("%3d%3d%3d%5d\n" % (6, 28, 9, 2026) + rows)
    return op.read_nod_equi(tmp_path / "stofs_2d_glo_nod_equi")[1]


def _check(tmp_path, script, got):
    want = _run(tmp_path / "bash", script)
    assert got.encode() == want


# ihot parity: 368 for 583200 and 594000 at 3 h, 367 for 572400 and 561600 MJ (10/05/26)
@pytest.mark.parametrize("stream,segment,time_hot,ncsth", [
    ("tide", "ncst", 583200, 6), ("surf", "ncst", 572400, 6),
    ("tide", "fcst1", 583200, 6), ("surf", "fcst1", 572400, 6),
    ("tide", "fcst2", 594000, 12), ("surf", "fcst2", 561600, 6)])
def test_segment_matches_ops_sed(tmp_path, stream, segment, time_hot, ncsth):
    nod = _nod(tmp_path)
    seg = op.ncst_segment(stream, str(time_hot), ncsth)
    for name in ("fcst1", "fcst2")[:("ncst", "fcst1", "fcst2").index(segment)]:
        seg = op.fcst_segment(stream, name, seg.state_time, seg.tokens["touts"], seg.tokens["toutf"])
    got = op.render((DATA / f"stofs_2d_glo_{stream}.15").read_text(), nod, seg.tokens, NOW)
    _check(tmp_path, _bash(stream, segment, time_hot, ncsth), got)
    assert [ln for ln in got.splitlines() if ln.endswith("! IHOT")][0].split()[0] == seg.tokens["ihot"]


def test_spinup_matches_ops_sed(tmp_path):
    nod = _nod(tmp_path)
    script = ("set -e\nRUN=stofs_2d_glo\ntime_spi=2026092806\n" + SPINUP
              + "cp %s ${RUN}_fort.15\n" % (DATA / "stofs_2d_glo_tide.15") + READ_NOD + SED_ADCPREP)
    _check(tmp_path, script, op.render((DATA / "stofs_2d_glo_tide.15").read_text(), nod, op.spinup_tokens(),
                                       "2026092806"))
