"""Join the nowcast and forecast staout_1 into the continuous series ops writes to $COMOUT/staout_1.

Ops runs one continuous SCHISM run per cycle, its time axis starting at the nowcast start, and
copies that run's staout_1 to $COMOUT; the next cycle's dynamic SSH adjust reads it as
$COMOUT_PREV/staout_1. nos-workflow runs the nowcast and the forecast as two SCHISM runs and the
forecast (ihot=1) restarts the clock, so the forecast rows are advanced by the nowcast length and
appended to the nowcast rows.

    python3 -m nos_workflow.tools.build_staout_1 \
        --comout $COMOUT --run stofs_3d_atl_ufs --cyc 12 [--nowcast-hours 24] [--pdy YYYYMMDD] \
        [--avg-bias-file FILE]

Inputs are <run>.<cycle>.restart_outputs/staout_1 and <run>.<cycle>.forecast_outputs/staout_1 (the
runner's per-phase archive) and the time_hotstart / time_nowcastend markers prep wrote (the same
ones that set each phase's start). If an input is missing nothing is written, and the next cycle
applies no previous-cycle bias, as ops does without a previous staout_1. --avg-bias-file seeds
rerun/<run>.<cycle>.avg_bias when backfilling a COMOUT written before prep archived it.
MJ (10/03/26)
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_ROW = re.compile(r"^(\s*)(\S+)(.*)$")
_FORTRAN_E = re.compile(r"^[+-]?0?\.(\d+)[Ee][+-]\d+$")


def is_atl_run(run: Optional[str]) -> bool:
    return (run or "").lower().startswith("stofs_3d_atl")


def previous_comout(comout, run: str, pdy: str) -> Path:
    prev = datetime.strptime(pdy, "%Y%m%d") - timedelta(days=1)
    return Path(comout).parent / ("%s.%s" % (run, prev.strftime("%Y%m%d")))


def _fortran_e(value: float, decimals: int) -> str:
    """Format as Fortran Ew.d does: 0.ddd...E+xx. MJ (10/03/26)"""
    if value == 0:
        return "0." + "0" * decimals + "E+00"
    mant, exp = ("%.*E" % (decimals - 1, abs(value))).split("E")
    return "%s0.%sE%+03d" % ("-" if value < 0 else "", mant.replace(".", ""), int(exp) + 1)


def _shift_line(line: str, shift_s: float) -> str:
    lead, token, rest = _ROW.match(line).groups()
    fmt = _FORTRAN_E.match(token)
    if fmt is None:
        raise ValueError("unrecognised staout_1 time field %r" % token)
    new = _fortran_e(float(token) + shift_s, len(fmt.group(1)))
    return new.rjust(len(lead) + len(token)) + rest


def _read_rows(path: Path) -> List[Tuple[float, str, int]]:
    rows = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            rows.append((float(_ROW.match(line).group(2)), line, len(line.split())))
    return rows


def join_staout_1(nowcast: Path, forecast: Path, shift_s: float) -> Tuple[str, int]:
    """Append the forecast rows, time advanced by shift_s, to the nowcast rows.

    Nowcast rows pass through verbatim. A forecast row at or before the last nowcast time
    (the shared boundary instant) is dropped. Returns (text, n_rows_dropped); raises
    ValueError on an empty file or differing column counts. MJ (10/03/26)
    """
    now, fcst = _read_rows(nowcast), _read_rows(forecast)
    if not now or not fcst:
        raise ValueError("empty staout_1 (nowcast rows=%d, forecast rows=%d)" % (len(now), len(fcst)))
    ncol = now[0][2]
    if any(r[2] != ncol for r in now + fcst):
        raise ValueError("staout_1 rows differ in column count (expected %d)" % ncol)
    last = now[-1][0]
    keep = [r for r in fcst if r[0] + shift_s > last]
    lines = [r[1] for r in now] + [_shift_line(r[1], shift_s) for r in keep]
    return "\n".join(lines) + "\n", len(fcst) - len(keep)


def _marker(comout: Path, name: str, cycle: str) -> Optional[datetime]:
    try:
        return datetime.strptime((comout / ("%s.%s" % (name, cycle))).read_text().strip()[:10], "%Y%m%d%H")
    except (OSError, ValueError):
        return None


def _nowcast_length_s(comout: Path, cycle: str, nowcast_hours: int, pdy: Optional[str]) -> float:
    """Nowcast length from the prep markers, else from nowcast_hours. MJ (10/03/26)"""
    start = _marker(comout, "time_hotstart", cycle)
    end = _marker(comout, "time_nowcastend", cycle)
    if start is None or end is None:
        if not pdy:
            m = re.search(r"\.(\d{8})$", comout.name)
            pdy = m.group(1) if m else None
        if not pdy:
            raise ValueError("no time markers in %s and no PDY to anchor the nowcast" % comout)
        cycle_dt = datetime.strptime(pdy, "%Y%m%d") + timedelta(hours=int(cycle[1:3]))
        end = end or cycle_dt
        start = start or end - timedelta(hours=nowcast_hours)
    if end <= start:
        raise ValueError("nowcast start %s is not before its end %s" % (start, end))
    return (end - start).total_seconds()


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(str(tmp), str(path))


def build_staout_1(
    comout,
    run: str,
    cyc,
    nowcast_hours: int = 24,
    pdy: Optional[str] = None,
    avg_bias_file: Optional[str] = None,
) -> Optional[Path]:
    """Write <comout>/staout_1 and return its path, or None when skipped.

    nowcast_hours and pdy only matter when the prep time markers are absent. MJ (10/03/26)
    """
    comout = Path(comout)
    cycle = "t%02dz" % int(cyc)
    now = comout / ("%s.%s.restart_outputs" % (run, cycle)) / "staout_1"
    fcst = comout / ("%s.%s.forecast_outputs" % (run, cycle)) / "staout_1"
    missing = [str(p) for p in (now, fcst) if not p.is_file()]
    if missing:
        logger.warning("build_staout_1: nothing written, missing %s; the next cycle gets no "
                       "previous-cycle bias", ", ".join(missing))
        return None
    try:
        shift_s = _nowcast_length_s(comout, cycle, nowcast_hours, pdy)
        text, n_dup = join_staout_1(now, fcst, shift_s)
    except (OSError, ValueError) as exc:
        logger.warning("build_staout_1: nothing written (%s); the next cycle gets no "
                       "previous-cycle bias", exc)
        return None

    out = comout / "staout_1"
    _atomic_write(out, text)
    if avg_bias_file:
        rerun = comout / "rerun"
        rerun.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(avg_bias_file), str(rerun / ("%s.%s.avg_bias" % (run, cycle))))
        except shutil.SameFileError:
            pass
        except OSError as exc:
            logger.warning("build_staout_1: could not copy %s (%s)", avg_bias_file, exc)
    logger.info("build_staout_1: wrote %s (forecast shifted %d s, %d rows, %d boundary row(s) "
                "dropped)", out, shift_s, text.count("\n"), n_dup)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--comout", required=True, help="cycle COMOUT, <COMOUTroot>/<run>.<PDY>")
    ap.add_argument("--run", required=True, help="run name, e.g. stofs_3d_atl_ufs")
    ap.add_argument("--cyc", required=True, help="cycle hour, e.g. 12")
    ap.add_argument("--nowcast-hours", type=int, default=24,
                    help="nowcast length, used only when the time markers are missing")
    ap.add_argument("--pdy", help="YYYYMMDD, used only when the markers are missing and COMOUT "
                                  "is not named <run>.<PDY>")
    ap.add_argument("--avg-bias-file", help="copy this file to rerun/<run>.t<cyc>z.avg_bias")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    done = build_staout_1(args.comout, args.run, args.cyc, args.nowcast_hours, args.pdy,
                          args.avg_bias_file)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
