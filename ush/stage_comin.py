#!/usr/bin/env python3
"""
Stage NOAA NODD S3 inputs into a COMIN-shaped tree for running the nos_ofs
workflow on Hercules, which has no COMIN trees.

Manifest builders mirror the file-discovery logic in
ush/python/nos-utils/nos_utils/forcing/{gfs,hrrr,rtofs,nwm}.py so files land
exactly where the workflow's COMINgfs/COMINhrrr/COMINrtofs/COMINnwm path
logic (dated subdirs under each COMIN root) expects them. Defaults match
parm/systems/secofs_ufs.yaml (nowcast_hours=6, forecast_hours=48,
rtofs_3d_region=US_east, river.hourly_extra_hours=18).

stdlib only: urllib for HTTPS, concurrent.futures for bounded parallel
downloads. No boto3, no aws-cli.
"""
import argparse
import concurrent.futures
import datetime as dt
import os
import sys
import time
import urllib.error
import urllib.request

BUCKETS = {
    "gfs": "noaa-gfs-bdp-pds",
    "hrrr": "noaa-hrrr-bdp-pds",
    "rtofs": "noaa-nws-rtofs-pds",
    "nwm": "noaa-nwm-pds",
}

HOUR = dt.timedelta(hours=1)


def s3_url(source, key):
    return f"https://{BUCKETS[source]}.s3.amazonaws.com/{key}"


def cycle_dt(pdy, cyc):
    return dt.datetime.strptime(pdy, "%Y%m%d") + dt.timedelta(hours=cyc)


def snap6(t):
    """Snap a datetime down to its 6-hourly GFS/NWM cycle (00/06/12/18Z)."""
    hour = t.hour - (t.hour % 6)
    return t.replace(hour=0, minute=0, second=0, microsecond=0), hour


# ---------------------------------------------------------------------------
# Manifest builders — one function per source, returning COMIN-relative keys
# (e.g. "gfs.20260825/12/atmos/gfs.t12z.pgrb2.0p25.f000") rooted at that
# source's own COMIN dir, matching gfs.py/hrrr.py/rtofs.py/nwm.py globs.
# ---------------------------------------------------------------------------

def manifest_gfs(pdy, cyc, nowcast_hours, forecast_hours, resolution="0p25", nws=4):
    """Mirrors GFSProcessor._compute_search_cycles + _build_file_list
    (nos_utils/forcing/gfs.py:460-716): union of the nowcast-branch cycles
    (walk back from cycle_dt to cover the nowcast window with a 3h buffer)
    and the forecast-branch cycles (current cycle + fallback cycles back to
    cycle_dt - nowcast_hours, +1 margin cycle for nws=4), each searched out
    to the forecast horizon.
    """
    c0 = cycle_dt(pdy, cyc)
    cycles = set()

    nowcast_start = c0 - dt.timedelta(hours=nowcast_hours) - dt.timedelta(hours=3)
    t = c0
    while t >= nowcast_start - dt.timedelta(hours=6):
        cycles.add(snap6(t))
        t -= dt.timedelta(hours=6)

    lookback_start = c0 - dt.timedelta(hours=nowcast_hours) if nws == 4 else c0 - dt.timedelta(hours=3)
    cycles.add(snap6(c0))
    margin = 1 if nws == 4 else 0
    t = c0 - dt.timedelta(hours=6)
    while True:
        date, hour = snap6(t)
        cycles.add((date, hour))
        if date + dt.timedelta(hours=hour) <= lookback_start:
            if margin > 0:
                margin -= 1
                t -= dt.timedelta(hours=6)
                continue
            break
        t -= dt.timedelta(hours=6)

    forecast_end = c0 + dt.timedelta(hours=forecast_hours) + dt.timedelta(hours=3)
    keys = []
    for date, hour in cycles:
        cycle_start = date + dt.timedelta(hours=hour)
        max_fhr = int((forecast_end - cycle_start).total_seconds() / 3600)
        max_fhr = max(max_fhr, forecast_hours + 3, 0)
        for fhr in range(0, max_fhr + 1):
            keys.append(
                f"gfs.{date:%Y%m%d}/{hour:02d}/atmos/"
                f"gfs.t{hour:02d}z.pgrb2.{resolution}.f{fhr:03d}"
            )
    return sorted(set(keys))


def manifest_hrrr(pdy, cyc, nowcast_hours, forecast_hours, max_forecast_hours=48):
    """Mirrors HRRRProcessor.find_input_files (nos_utils/forcing/hrrr.py:196-240):
    hourly f01 lookback covering the nowcast window (one extra hour back so a
    HRRR field lands exactly at model_t0), then f01..f<forecast_hours> from
    the current cycle.
    """
    c0 = cycle_dt(pdy, cyc)

    def key(date, cycle_hour, fhr):
        return f"hrrr.{date:%Y%m%d}/conus/hrrr.t{cycle_hour:02d}z.wrfsfcf{fhr:02d}.grib2"

    keys = []
    nowcast_start_hour = cyc - nowcast_hours - 1
    if nowcast_start_hour < 0:
        prev_date = c0 - dt.timedelta(days=1)
        for hr in range(24 + nowcast_start_hour, 24):
            keys.append(key(prev_date, hr, 1))
        for hr in range(0, cyc):
            keys.append(key(c0, hr, 1))
    else:
        for hr in range(nowcast_start_hour, cyc):
            keys.append(key(c0, hr, 1))

    max_fhr = min(forecast_hours, max_forecast_hours)
    for fhr in range(1, max_fhr + 1):
        keys.append(key(c0, cyc, fhr))
    return sorted(set(keys))


def _rtofs_2d_lead(offset_hours):
    """RTOFS 2D diag product is hourly through f072, then 3-hourly (verified
    against noaa-nws-rtofs-pds on 2026-08-25: last hourly file is f072, next
    is f075). Snap any offset beyond 72 to the nearest published 3h lead.
    """
    if offset_hours <= 72:
        return offset_hours
    lead = int(round(offset_hours / 3.0)) * 3
    return max(75, min(192, lead))


def resolve_rtofs_date(pdy, probe):
    """Pick the RTOFS cycle date (00Z) to read from, mirroring the exact
    search order in RTOFSProcessor.find_input_files_by_type
    (nos_utils/forcing/rtofs.py:1207-1212):

        # Search newest RTOFS cycle first to match Fortran shell behavior.
        # The Fortran prep (nos_ofs_create_forcing_obc.sh) uses the latest
        # available cycle. PDY itself rarely has RTOFS ready at 00Z, so
        # PDY-1 is the typical production hit.
        for date in [base_date - timedelta(days=1),
                     base_date - timedelta(days=2), base_date]:

    i.e. PDY-1, then PDY-2, then PDY last — exactly 3 candidates, in that
    order (not chronological: PDY is checked last despite being newest).
    ``probe`` is a callable(url) -> bool; the default (head_probe) issues one
    HTTPS HEAD per candidate against the cheapest expected key (the 2ds f000
    file) and stops at the first hit.

    Returns (date, candidates, found). When every candidate probe fails,
    falls back to candidates[0] (PDY-1, the old hardcoded default) with
    found=False so the caller can warn instead of silently guessing.
    """
    base_date = dt.datetime.strptime(pdy, "%Y%m%d")
    candidates = [
        base_date - dt.timedelta(days=1),
        base_date - dt.timedelta(days=2),
        base_date,
    ]
    for date in candidates:
        probe_key = f"rtofs.{date:%Y%m%d}/rtofs_glo_2ds_f000_diag.nc"
        if probe(s3_url("rtofs", probe_key)):
            return date, candidates, True
    return candidates[0], candidates, False


def head_probe(url, timeout=15):
    """Default probe for resolve_rtofs_date: one HEAD request, True on any
    successful response, False on 404 or any network error.
    """
    try:
        head_content_length(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def manifest_rtofs(pdy, cyc, nowcast_hours, forecast_hours, region="US_east",
                    buffer_hours=6, rtofs_date=None):
    """Mirrors RTOFSProcessor.find_input_files_by_type + _sort_and_dedup
    (nos_utils/forcing/rtofs.py:287-304, 1143-1367).

    rtofs_date is the resolved RTOFS cycle date (00Z); see
    resolve_rtofs_date for the PDY-1/PDY-2/PDY probe order this mirrors.
    When not supplied (e.g. calling this function directly, without going
    through build_manifest's probe), defaults to PDY-1 — the same value
    resolve_rtofs_date returns before any probe runs.

    Both n-tag (nowcast) and f-tag (forecast) files can cover the same valid
    time; _sort_and_dedup's tuple sort key (valid_time, is_nowcast) makes a
    forecast file win any tie (matches the legacy Fortran shell, which only
    ever collects f* files) — so only f-tag files need staging.
    """
    c0 = cycle_dt(pdy, cyc)
    if rtofs_date is None:
        rtofs_date = c0.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)
    window_start = c0 - dt.timedelta(hours=nowcast_hours) - dt.timedelta(hours=buffer_hours)
    window_end = c0 + dt.timedelta(hours=forecast_hours) + dt.timedelta(hours=buffer_hours)
    off_start = int((window_start - rtofs_date).total_seconds() / 3600)
    off_end = int((window_end - rtofs_date).total_seconds() / 3600)

    keys = []
    for off in range(max(off_start, 0), max(off_end, 0) + 1):
        lead = _rtofs_2d_lead(off)
        keys.append(f"rtofs.{rtofs_date:%Y%m%d}/rtofs_glo_2ds_f{lead:03d}_diag.nc")

    off3_start = max(6, (max(off_start, 0) // 6) * 6)
    off3_end = min(192, -(-max(off_end, 0) // 6) * 6)
    for off in range(off3_start, off3_end + 1, 6):
        keys.append(
            f"rtofs.{rtofs_date:%Y%m%d}/rtofs_glo_3dz_f{off:03d}_6hrly_hvr_{region}.nc"
        )
    return sorted(set(keys))


def manifest_nwm(pdy, cyc, nowcast_hours, forecast_hours, buffer_hours=3,
                  extra_hours=18, short_range_max_lead=18):
    """Mirrors NWMProcessor._find_secofs_nwm_files (default nwm_product=
    analysis_assim, nos_utils/forcing/nwm.py:738-818): observed analysis for
    the nowcast window, NWM forecast for the window tail.

    Simplifications vs. the runtime discovery code (both verified against
    the actual product, not assumed):
      - Only tm00 (on-the-hour) analysis_assim files are staged, one per
        nowcast hour, rather than every tm* present -- the runtime code
        globs all tm* it finds but keeps one file per hour downstream.
      - short_range/medium_range_mem1 are read from the model cycle itself
        (pdy/cyc), not from a multi-cycle frontier search. This is exact
        for SECOFS/STOFS, whose cycles always land on 00/06/12/18Z, the
        same hours NWM issues short_range and medium_range_mem1.
      - short_range_max_lead=18 was confirmed against noaa-nwm-pds for a
        00/06/12/18Z cycle (2026-08-25 t12z: last short_range lead f018).

    total_hours (extra_hours) mirrors production COMF's NWM window extension
    past the simulation end (nos_ofs_create_forcing_river.sh:86, time_end =
    NDATE 72 time_hotstart) -- for SECOFS-UFS (nowcast=6, forecast=48) that
    is 18h past the forecast end, wired through river.hourly_extra_hours in
    parm/systems/secofs_ufs.yaml.
    """
    c0 = cycle_dt(pdy, cyc)
    keys = []

    h = c0 - dt.timedelta(hours=nowcast_hours)
    while h <= c0:
        keys.append(
            f"nwm.{h:%Y%m%d}/analysis_assim/"
            f"nwm.t{h.hour:02d}z.analysis_assim.channel_rt.tm00.conus.nc"
        )
        h += HOUR

    window_hours = forecast_hours + buffer_hours + extra_hours
    for lead in range(1, min(window_hours, short_range_max_lead) + 1):
        keys.append(
            f"nwm.{c0:%Y%m%d}/short_range/"
            f"nwm.t{cyc:02d}z.short_range.channel_rt.f{lead:03d}.conus.nc"
        )
    for lead in range(short_range_max_lead + 1, window_hours + 1):
        keys.append(
            f"nwm.{c0:%Y%m%d}/medium_range_mem1/"
            f"nwm.t{cyc:02d}z.medium_range.channel_rt_1.f{lead:03d}.conus.nc"
        )
    return sorted(set(keys))


MANIFEST_BUILDERS = {
    "gfs": manifest_gfs,
    "hrrr": manifest_hrrr,
    "rtofs": manifest_rtofs,
    "nwm": manifest_nwm,
}


def build_manifest(sources, pdy, cyc, nowcast_hours, forecast_hours, comroot,
                    rtofs_region="US_east", rtofs_probe=head_probe):
    """Returns [(url, local_path), ...]. Each source lands under
    comroot/<source>/ so that dir can be pointed to directly as
    COMINgfs/COMINhrrr/COMINrtofs/COMINnwm (each already contains the dated
    gfs.YYYYMMDD/... hrrr.YYYYMMDD/... etc. subdirs the workflow expects).

    rtofs_probe is threaded through to resolve_rtofs_date so callers (tests,
    --no-probe) can swap in a fake probe without any network use.
    """
    entries = []
    for source in sources:
        if source == "rtofs":
            rtofs_date, candidates, found = resolve_rtofs_date(pdy, rtofs_probe)
            if not found:
                tried = ", ".join(d.strftime("%Y%m%d") for d in candidates)
                print(
                    f"warning: RTOFS probe found no published cycle at any "
                    f"of {tried}; defaulting manifest to {candidates[0]:%Y%m%d} "
                    f"(PDY-1) -- downloads will report these files missing "
                    f"if that date is not actually published",
                    file=sys.stderr,
                )
            keys = manifest_rtofs(pdy, cyc, nowcast_hours, forecast_hours,
                                   region=rtofs_region, rtofs_date=rtofs_date)
        else:
            keys = MANIFEST_BUILDERS[source](pdy, cyc, nowcast_hours, forecast_hours)
        for key in keys:
            entries.append((s3_url(source, key), os.path.join(comroot, source, key)))
    return entries


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def head_content_length(url, timeout=15):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        length = resp.headers.get("Content-Length")
        return int(length) if length is not None else None


def download_one(url, local_path, retries=3, backoff=2.0, timeout=120):
    try:
        remote_size = head_content_length(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "missing", f"404: {url}"
        remote_size = None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        remote_size = None
        head_err = str(e)
    else:
        head_err = None

    if remote_size is not None and os.path.exists(local_path):
        if os.path.getsize(local_path) == remote_size:
            return "skipped", None

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    tmp_path = local_path + ".part"

    last_err = head_err
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp_path, "wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp_path, local_path)
            return "downloaded", None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _cleanup(tmp_path)
                return "missing", f"404: {url}"
            last_err = f"HTTP {e.code}: {url}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"

        _cleanup(tmp_path)
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))

    return "failed", last_err


def _cleanup(tmp_path):
    try:
        os.remove(tmp_path)
    except OSError:
        pass


def stage(manifest, jobs=8, retries=3, timeout=120):
    results = {"downloaded": [], "skipped": [], "missing": [], "failed": []}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(download_one, url, local, retries, 2.0, timeout): (url, local)
            for url, local in manifest
        }
        for fut in concurrent.futures.as_completed(futures):
            url, local = futures[fut]
            status, err = fut.result()
            results[status].append((url, local, err))
            print(f"[{status}] {url}", flush=True)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdy", required=True, help="YYYYMMDD")
    p.add_argument("--cyc", required=True, type=int, help="cycle hour (0/6/12/18)")
    p.add_argument("--comroot", required=True, help="root dir for the staged COMIN-shaped tree")
    p.add_argument("--sources", default="gfs,hrrr,rtofs,nwm",
                    help="comma-separated subset of gfs,hrrr,rtofs,nwm")
    p.add_argument("--nowcast-hours", type=int, default=6,
                    help="default matches parm/systems/secofs_ufs.yaml model.run.nowcast_hours")
    p.add_argument("--forecast-hours", type=int, default=48,
                    help="default matches parm/systems/secofs_ufs.yaml model.run.forecast_hours")
    p.add_argument("--rtofs-region", default="US_east",
                    help="default matches secofs_ufs.yaml forcing.ocean.rtofs_3d_region")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-probe", action="store_true",
                    help="skip the RTOFS cycle-date HEAD probe entirely and "
                         "assume PDY-1 (fully offline manifest inspection)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = set(sources) - set(MANIFEST_BUILDERS)
    if unknown:
        print(f"unknown source(s): {sorted(unknown)}", file=sys.stderr)
        return 2

    # --no-probe: first candidate (PDY-1) always "found", no network at all.
    rtofs_probe = (lambda url: True) if args.no_probe else head_probe

    manifest = build_manifest(
        sources, args.pdy, args.cyc, args.nowcast_hours, args.forecast_hours,
        args.comroot, rtofs_region=args.rtofs_region, rtofs_probe=rtofs_probe,
    )

    if args.dry_run:
        for url, local in manifest:
            print(f"{url} -> {local}")
        print(f"\n{len(manifest)} files in manifest", file=sys.stderr)
        return 0

    results = stage(manifest, jobs=args.jobs)

    total = len(manifest)
    print(
        f"\nsummary: {total} files -- "
        f"downloaded={len(results['downloaded'])} "
        f"skipped={len(results['skipped'])} "
        f"missing={len(results['missing'])} "
        f"failed={len(results['failed'])}",
        file=sys.stderr,
    )
    if results["missing"] or results["failed"]:
        print("\nnot staged:", file=sys.stderr)
        for status in ("missing", "failed"):
            for url, local, err in results[status]:
                print(f"  [{status}] {url} ({err})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
