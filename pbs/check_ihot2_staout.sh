#!/bin/bash
#==========================================================================
# Sanity check for ihot=2 forecast staout_1 output
#
# Reads the first N records after the nowcast→forecast transition and
# checks for water level spikes that indicate the ghost node pressure bug.
#
# Usage:
#   ./check_ihot2_staout.sh /path/to/rundir
#   ./check_ihot2_staout.sh   # uses default RUNDIR below
#
# What it checks:
#   1. staout_1 exists and has enough lines
#   2. Water levels at transition are continuous (no sudden jumps)
#   3. Max |WL| stays below 2.0m (SECOFS normal range: -0.5 to +1.0m)
#   4. Step-to-step change stays below 0.5m (physical limit for 6-min output)
#   5. Compares last nowcast record vs first forecast records
#
# SECOFS timing:
#   dt=120s, nspool_sta=3 → output every 360s (6 min)
#   ihot=2 nowcast: 180 steps → 60 records (6 hours)
#   Forecast starts at record 61
#==========================================================================

RUNDIR=${1:-/lfs/h1/nos/ptmp/mansur.jisan/work/v3.7.0/secofs_ufs/secofs_ufs_nc_00_dev.97829204.dbqs01}

# SECOFS parameters
DT=120
NSPOOL_STA=3
OUTPUT_INTERVAL=$((DT * NSPOOL_STA))  # 360s = 6 min
NOWCAST_HOURS=6
NOWCAST_RECORDS=$((NOWCAST_HOURS * 3600 / OUTPUT_INTERVAL))  # 60

# Thresholds
MAX_WL=2.0        # Max absolute water level (m) — SECOFS normal: -0.5 to +1.0
MAX_JUMP=0.5      # Max step-to-step change (m) — physical limit for 6-min output
SPIKE_THRESHOLD=3.0  # Definite blowup indicator

echo "============================================"
echo "  ihot=2 Forecast Sanity Check"
echo "============================================"
echo "RUNDIR: $RUNDIR"
echo "Date: $(date -u)"
echo ""

cd "$RUNDIR" || { echo "FATAL: Cannot cd to $RUNDIR"; exit 1; }

#--- Check ESMF log for the fix ---
echo "=== 1. Checking ESMF log for ihot=2 fix ==="
if [ -f PET0000.ESMF_LogFile ]; then
    FIX_LINE=$(grep -m1 "IHOT2_DEBUG\|first-call ATM fix" PET0000.ESMF_LogFile 2>/dev/null)
    if [ -n "$FIX_LINE" ]; then
        echo "  GOOD: Fix detected in ESMF log:"
        echo "  $FIX_LINE"
    else
        echo "  WARNING: No ihot=2 fix message found in ESMF log"
        echo "  The executable may not have the ghost exchange fix!"
    fi
else
    echo "  (No PET0000.ESMF_LogFile found — run may not have started)"
fi
echo ""

#--- Check stderr for debug output ---
echo "=== 2. Checking stderr for debug output ==="
for f in *.err PET0000.ESMF_LogFile; do
    [ -f "$f" ] || continue
    WTIME=$(grep -m1 "IHOT2_DEBUG" "$f" 2>/dev/null)
    if [ -n "$WTIME" ]; then
        echo "  Found in $f:"
        echo "  $WTIME"
        # Parse wtime1 value
        WT1=$(echo "$WTIME" | grep -oP 'wtime1=\s*\K[0-9.E+]+' | head -1)
        if [ -n "$WT1" ]; then
            echo "  wtime1=$WT1 (should be ~21600 for 6hr nowcast)"
        fi
        break
    fi
done
echo ""

#--- Check fatal.error ---
echo "=== 3. Checking for crashes ==="
if [ -f fatal.error ]; then
    echo "  CRASH DETECTED:"
    cat fatal.error
    echo ""
    echo "  Check PET*.ESMF_LogFile for details"
else
    echo "  OK: No fatal.error file"
fi

if [ -f mirror.out ]; then
    echo "  OK: mirror.out exists (model completed)"
else
    echo "  WARNING: No mirror.out (model may still be running or crashed)"
fi
echo ""

#--- Check staout_1 ---
echo "=== 4. Checking staout_1 ==="
STAOUT=outputs/staout_1
if [ ! -f "$STAOUT" ]; then
    echo "  FATAL: $STAOUT not found!"
    exit 1
fi

TOTAL_LINES=$(wc -l < "$STAOUT")
echo "  Total records: $TOTAL_LINES"
echo "  Expected nowcast records: $NOWCAST_RECORDS"

if [ "$TOTAL_LINES" -lt "$NOWCAST_RECORDS" ]; then
    echo "  WARNING: Fewer records than nowcast period — forecast may not have started"
fi

#--- Show transition region ---
echo ""
echo "=== 5. Nowcast→Forecast transition (records $((NOWCAST_RECORDS-4)) to $((NOWCAST_RECORDS+20))) ==="
echo "  Record format: time(s)  station1_WL  station2_WL  ..."
echo ""
echo "  --- Last 5 nowcast records ---"
# Show columns: record#, time, first 3 station water levels
awk -v start=$((NOWCAST_RECORDS-4)) -v end=$NOWCAST_RECORDS \
    'NR>=start && NR<=end {
        printf "  rec %4d | t=%8.0f | WL:", NR, $1
        for(i=2; i<=4 && i<=NF; i++) printf " %8.4f", $i
        print ""
    }' "$STAOUT"

echo ""
echo "  --- First 20 forecast records ---"
awk -v start=$((NOWCAST_RECORDS+1)) -v end=$((NOWCAST_RECORDS+20)) \
    'NR>=start && NR<=end {
        printf "  rec %4d | t=%8.0f | WL:", NR, $1
        for(i=2; i<=4 && i<=NF; i++) printf " %8.4f", $i
        print ""
    }' "$STAOUT"

#--- Analyze water levels at all stations ---
echo ""
echo "=== 6. Water level analysis (all stations, all records) ==="

# Use awk to analyze: max WL, max jump, spike detection
awk -v nowcast_rec="$NOWCAST_RECORDS" \
    -v max_wl="$MAX_WL" \
    -v max_jump="$MAX_JUMP" \
    -v spike_thresh="$SPIKE_THRESHOLD" \
    -v dt_out="$OUTPUT_INTERVAL" \
'
BEGIN {
    n_stations = 0
    max_abs_wl = 0
    max_abs_wl_rec = 0
    max_abs_wl_sta = 0
    max_step_jump = 0
    max_jump_rec = 0
    max_jump_sta = 0
    spike_count = 0
    transition_max_jump = 0
    n_fcst_records = 0
}
NR == 1 {
    n_stations = NF - 1
    for (i = 2; i <= NF; i++) prev[i] = $i
    next
}
{
    rec = NR
    time = $1

    # Count forecast records
    if (rec > nowcast_rec) n_fcst_records++

    for (i = 2; i <= NF; i++) {
        wl = $i + 0.0
        abs_wl = (wl < 0) ? -wl : wl

        # Track max absolute WL
        if (abs_wl > max_abs_wl) {
            max_abs_wl = abs_wl
            max_abs_wl_rec = rec
            max_abs_wl_sta = i - 1
            max_abs_wl_time = time
        }

        # Track step-to-step jumps
        jump = wl - prev[i]
        abs_jump = (jump < 0) ? -jump : jump
        if (abs_jump > max_step_jump) {
            max_step_jump = abs_jump
            max_jump_rec = rec
            max_jump_sta = i - 1
            max_jump_time = time
        }

        # Track transition jump specifically (rec 60→61)
        if (rec == nowcast_rec + 1) {
            if (abs_jump > transition_max_jump) {
                transition_max_jump = abs_jump
                transition_sta = i - 1
            }
        }

        # Count spikes
        if (abs_wl > spike_thresh) spike_count++

        prev[i] = wl
    }
}
END {
    printf "  Stations: %d\n", n_stations
    printf "  Total records: %d (nowcast: %d, forecast: %d)\n", NR, nowcast_rec, n_fcst_records
    printf "\n"

    printf "  Max |WL|: %.4f m at record %d (t=%.0fs, station %d)\n", \
        max_abs_wl, max_abs_wl_rec, max_abs_wl_time, max_abs_wl_sta
    if (max_abs_wl > max_wl) {
        printf "    *** FAIL: Exceeds threshold %.1f m ***\n", max_wl
    } else {
        printf "    PASS: Within threshold (< %.1f m)\n", max_wl
    }
    printf "\n"

    printf "  Max step-to-step jump: %.4f m at record %d (t=%.0fs, station %d)\n", \
        max_step_jump, max_jump_rec, max_jump_time, max_jump_sta
    if (max_step_jump > max_jump) {
        printf "    *** FAIL: Exceeds threshold %.1f m ***\n", max_jump
    } else {
        printf "    PASS: Within threshold (< %.1f m)\n", max_jump
    }
    printf "\n"

    printf "  Transition jump (rec %d→%d): %.4f m (station %d)\n", \
        nowcast_rec, nowcast_rec+1, transition_max_jump, transition_sta
    if (transition_max_jump > max_jump) {
        printf "    *** FAIL: Discontinuity at nowcast→forecast boundary! ***\n"
    } else {
        printf "    PASS: Smooth transition\n"
    }
    printf "\n"

    if (spike_count > 0) {
        printf "  *** SPIKE ALERT: %d values exceed %.1f m across all stations ***\n", \
            spike_count, spike_thresh
        printf "  This indicates the ghost node pressure bug is NOT fixed!\n"
    } else {
        printf "  No spikes detected (all values < %.1f m)\n", spike_thresh
    }
}
' "$STAOUT"

#--- Quick min/max per station for first 3 stations ---
echo ""
echo "=== 7. Per-station summary (first 3 stations) ==="
for STA in 1 2 3; do
    COL=$((STA + 1))
    awk -v col="$COL" -v sta="$STA" -v ncrec="$NOWCAST_RECORDS" '
    BEGIN { nc_min=999; nc_max=-999; fc_min=999; fc_max=-999 }
    {
        v = $col + 0.0
        if (NR <= ncrec) {
            if (v < nc_min) nc_min = v
            if (v > nc_max) nc_max = v
        } else {
            if (v < fc_min) fc_min = v
            if (v > fc_max) fc_max = v
        }
    }
    END {
        printf "  Station %d: nowcast [%+.3f, %+.3f]m  forecast [%+.3f, %+.3f]m\n", \
            sta, nc_min, nc_max, fc_min, fc_max
    }' "$STAOUT"
done

#--- Final verdict ---
echo ""
echo "============================================"
# Re-run the spike check for final verdict
SPIKE=$(awk -v thresh="$SPIKE_THRESHOLD" '
BEGIN { found = 0 }
{
    for (i=2; i<=NF; i++) {
        v = ($i < 0) ? -$i : $i
        if (v > thresh) { found = 1; exit }
    }
}
END { print (found ? "YES" : "NO") }
' "$STAOUT")

JUMP=$(awk -v thresh="$MAX_JUMP" -v ncrec="$NOWCAST_RECORDS" '
BEGIN { found = 0 }
NR == 1 { for(i=2;i<=NF;i++) p[i]=$i; next }
NR == ncrec+1 {
    for(i=2;i<=NF;i++) {
        d = $i - p[i]; if(d<0) d=-d
        if (d > thresh) { found = 1; exit }
    }
}
{ for(i=2;i<=NF;i++) p[i]=$i }
END { print (found ? "YES" : "NO") }
' "$STAOUT")

# Also check for spikes specifically in the FORECAST period (after nowcast)
FCST_SPIKE=$(awk -v thresh="$SPIKE_THRESHOLD" -v ncrec="$NOWCAST_RECORDS" '
BEGIN { found = 0 }
NR > ncrec {
    for (i=2; i<=NF; i++) {
        v = ($i < 0) ? -$i : $i
        if (v > thresh) { found = 1; exit }
    }
}
END { print (found ? "YES" : "NO") }
' "$STAOUT")

if [ "$FCST_SPIKE" = "YES" ]; then
    echo "  VERDICT: FAIL — Water level spike in FORECAST period!"
    echo "  The ghost node pressure bug is likely NOT fixed."
    echo "  Check that the rebuilt executable has the exchange_p2d calls."
    exit 1
elif [ "$JUMP" = "YES" ]; then
    echo "  VERDICT: WARNING — Large jump at nowcast→forecast transition"
    echo "  The wtime bracket fix may not be working correctly."
    echo "  Check ESMF log for 'IHOT2_DEBUG: first-call fix wtime1=21600'"
    exit 1
elif [ "$SPIKE" = "YES" ]; then
    echo "  VERDICT: WARNING — Spikes found in NOWCAST period (not at transition)"
    echo "  This is likely a spinup issue (e.g. shallow stations), not the ihot=2 bug."
    echo "  Forecast transition at records $NOWCAST_RECORDS→$((NOWCAST_RECORDS+1)) is smooth."
    exit 0
else
    echo "  VERDICT: PASS — ihot=2 forecast looks good!"
    echo "  Water levels are smooth through the transition."
    exit 0
fi
