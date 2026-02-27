#!/bin/bash
# =============================================================================
# Script Name: nos_ofs_create_datm_forcing.sh
#
# Purpose:
#   Create DATM forcing files by extracting and concatenating meteorological
#   variables from GFS/HRRR GRIB2 files for all forecast hours.
#   This creates time-series NetCDF files for use with UFS-Coastal CDEPS DATM.
#
#   The script uses the same Fortran file selection (nos_ofs_met_file_search)
#   as operational SFLUX generation to ensure consistency.
#
# Usage:
#   ./nos_ofs_create_datm_forcing.sh DBASE OUTPUT_DIR [TIME_START] [TIME_END]
#
# Arguments:
#   DBASE      - Data source: GFS25 or HRRR
#   OUTPUT_DIR - Directory for output files
#   TIME_START - Start time YYYYMMDDHH (optional, default: time_hotstart - 3h)
#   TIME_END   - End time YYYYMMDDHH (optional, default: time_forecastend)
#
# Environment Variables:
#   PDY        - Forecast date (YYYYMMDD)
#   cyc        - Forecast cycle (00, 06, 12, 18)
#   COMINgfs   - GFS input directory
#   COMINhrrr  - HRRR input directory
#   WGRIB2     - Path to wgrib2 executable
#   NDATE      - Path to ndate utility
#   NHOUR      - Path to nhour utility
#
# Logging Options (environment variables):
#   VERBOSE=0  - Quiet mode (minimal output)
#   VERBOSE=1  - Normal mode (default, shows progress)
#   VERBOSE=2  - Debug mode (shows all file selections)
#   LOG_FILE   - Path to save detailed log (optional)
#
# Output Files:
#   gfs_forcing.nc  - GFS forcing file (if DBASE=GFS25)
#   hrrr_forcing.nc - HRRR forcing file (if DBASE=HRRR)
#   datm_work_*     - Work directory with debug artifacts
#
# Author: SECOFS UFS-Coastal Transition
# Date: January 2026
# =============================================================================

set -x

# =============================================================================
# Parse Arguments
# =============================================================================
DBASE=$1
OUTPUT_DIR=$2
TIME_START=$3
TIME_END=$4

if [ -z "$DBASE" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "============================================"
    echo "Usage: $0 DBASE OUTPUT_DIR [TIME_START] [TIME_END]"
    echo ""
    echo "Arguments:"
    echo "  DBASE      - Data source: GFS25 or HRRR"
    echo "  OUTPUT_DIR - Directory for output files"
    echo "  TIME_START - Start time YYYYMMDDHH (optional)"
    echo "  TIME_END   - End time YYYYMMDDHH (optional)"
    echo ""
    echo "Environment Variables Required:"
    echo "  PDY, cyc, COMINgfs/COMINhrrr, WGRIB2, NDATE"
    echo ""
    echo "Logging Options (optional):"
    echo "  VERBOSE=0  - Quiet mode (minimal output)"
    echo "  VERBOSE=1  - Normal mode (default, shows progress)"
    echo "  VERBOSE=2  - Debug mode (shows all file selections)"
    echo "  LOG_FILE   - Path to save detailed log (optional)"
    echo ""
    echo "Example:"
    echo "  VERBOSE=2 LOG_FILE=datm.log $0 HRRR ./output"
    echo "============================================"
    exit 1
fi

# =============================================================================
# Setup Environment
# =============================================================================
WGRIB2=${WGRIB2:-wgrib2}
NDATE=${NDATE:-ndate}
NHOUR=${NHOUR:-nhour}
PDY=${PDY:-$(date +%Y%m%d)}
cyc=${cyc:-00}

# Logging options
VERBOSE=${VERBOSE:-1}           # 0=quiet, 1=normal, 2=verbose
LOG_FILE=${LOG_FILE:-""}        # Optional log file path

# Logging function
log_msg() {
    local level=$1
    shift
    local msg="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    if [ "$level" -le "$VERBOSE" ]; then
        echo "[$timestamp] $msg" >&2
        if [ -n "$LOG_FILE" ]; then
            echo "[$timestamp] $msg" >> "$LOG_FILE"
        fi
    fi
}

log_info() { log_msg 1 "INFO: $@"; }
log_debug() { log_msg 2 "DEBUG: $@"; }
log_warn() { log_msg 1 "WARN: $@"; }

# Default time range if not provided
if [ -z "$TIME_START" ]; then
    # Default: PDY + cyc - 6h (nowcast start) - 3h buffer = -9h from cycle
    TIME_START=$($NDATE -9 ${PDY}${cyc})
fi
if [ -z "$TIME_END" ]; then
    # Default: PDY + cyc + 48h
    TIME_END=$($NDATE 48 ${PDY}${cyc})
fi

mkdir -p $OUTPUT_DIR
TEMP_DIR=${OUTPUT_DIR}/temp_forcing_$$
mkdir -p $TEMP_DIR

# Normalize DBASE
DBASE_UPPER=$(echo $DBASE | tr '[:lower:]' '[:upper:]')
DBASE_LOWER=$(echo $DBASE | tr '[:upper:]' '[:lower:]')
if [ "$DBASE_LOWER" == "gfs25" ]; then
    DBASE_LOWER="gfs"
fi

# Calculate total hours
TOTAL_HOURS=$($NHOUR $TIME_END $TIME_START)

echo "============================================"
echo "DATM Forcing File Generation"
echo "============================================"
echo "DBASE:       $DBASE_UPPER"
echo "TIME_START:  $TIME_START"
echo "TIME_END:    $TIME_END"
echo "TOTAL_HOURS: $TOTAL_HOURS"
echo "OUTPUT_DIR:  $OUTPUT_DIR"
echo "TEMP_DIR:    $TEMP_DIR"
echo "============================================"

# =============================================================================
# Set Data Source Parameters
# =============================================================================
if [ "$DBASE_UPPER" == "GFS" ] || [ "$DBASE_UPPER" == "GFS25" ]; then
    INTERVAL=3
    COMIN=${COMINgfs:-/lfs/h1/ops/prod/com/gfs/v16.3}
    # GFS variables to extract
    MATCH_PATTERN=":(UGRD|VGRD):10 m above ground:|:(TMP|SPFH):2 m above ground:|:PRMSL:mean sea level:|:(DSWRF|DLWRF|PRATE):surface:"
    OUTPUT_FILE=${OUTPUT_DIR}/gfs_forcing.nc

elif [ "$DBASE_UPPER" == "HRRR" ]; then
    INTERVAL=1
    COMIN=${COMINhrrr:-/lfs/h1/ops/prod/com/hrrr/v4.1}
    # HRRR uses MSLMA instead of PRMSL
    MATCH_PATTERN=":(UGRD|VGRD):10 m above ground:|:(TMP|SPFH):2 m above ground:|:MSLMA:mean sea level:|:(DSWRF|DLWRF|PRATE):surface:"
    OUTPUT_FILE=${OUTPUT_DIR}/hrrr_forcing.nc
else
    echo "ERROR: Unknown DBASE: $DBASE"
    echo "Supported values: GFS, GFS25, HRRR"
    exit 1
fi

# =============================================================================
# Function: Find GFS file for a valid time
# Strategy: Use base cycle with extended forecasts (up to f120 = 5 days)
# =============================================================================
find_gfs_file() {
    local VALID_TIME=$1
    local VALID_DATE=$(echo $VALID_TIME | cut -c1-8)
    local VALID_HH=$(echo $VALID_TIME | cut -c9-10)

    # Calculate initial cycle (6 hours before valid time, rounded down to 00/06/12/18)
    local INIT_CYCLE_TIME=$($NDATE -6 $VALID_TIME)
    local INIT_DATE=$(echo $INIT_CYCLE_TIME | cut -c1-8)
    local INIT_HH=$(echo $INIT_CYCLE_TIME | cut -c9-10)
    local INIT_HH_NUM=$((10#$INIT_HH))

    # Round down to nearest 6-hourly cycle
    local CYCLE_HH=$(printf "%02d" $((INIT_HH_NUM / 6 * 6)))
    local CYCLE_DATE=$INIT_DATE
    local CYCLE_TIME="${CYCLE_DATE}${CYCLE_HH}"

    # Try up to 12 cycles (going back 72 hours)
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
        local FHR=$($NHOUR $VALID_TIME $CYCLE_TIME 2>/dev/null || echo "-1")
        local FHR_DEC=$((10#$FHR))
        if [ "$FHR_DEC" -ge 0 ] && [ "$FHR_DEC" -le 120 ]; then
            local FHR_STR=$(printf "%03d" $FHR_DEC)
            local GRIB2_FILE="${COMIN}/gfs.${CYCLE_DATE}/${CYCLE_HH}/atmos/gfs.t${CYCLE_HH}z.pgrb2.0p25.f${FHR_STR}"

            if [ -s "$GRIB2_FILE" ]; then
                echo "$GRIB2_FILE"
                return 0
            fi
        fi

        # Try previous cycle (6 hours earlier)
        CYCLE_TIME=$($NDATE -6 $CYCLE_TIME)
        CYCLE_DATE=$(echo $CYCLE_TIME | cut -c1-8)
        CYCLE_HH=$(echo $CYCLE_TIME | cut -c9-10)
    done

    echo ""
    return 1
}

# =============================================================================
# Function: Find HRRR files using Fortran executable (matches SFLUX exactly)
# Uses nos_ofs_met_file_search for operational consistency
# =============================================================================

# Track files used for logging
declare -a FILES_USED=()
HRRR_FILE_LIST=""

# Fortran executable path
MET_FILE_SEARCH=${EXECnos:-/lfs/h1/ops/prod/packages/nosofs.v3.7.0/exec}/nos_ofs_met_file_search

find_hrrr_files_fortran() {
    # ==========================================================================
    # Match COMF SFLUX file selection EXACTLY.
    #
    # COMF (nos_ofs_create_forcing_met.sh) builds tmp.out as follows:
    #   1. Loop cycles 0-23 on each date, check if f01 exists
    #   2. Add f01 to tmp.out for each detected cycle
    #   3. Track EXIST_CYCLE = latest cycle with f01 (nowcast)
    #      or latest cycle with f01 AND f48 (forecast)
    #   4. After detection, add f01-f22 (nowcast) or f01-f48 (forecast)
    #      from EXIST_CYCLE only
    #   5. Feed this narrow list to nos_ofs_met_file_search
    #
    # COMF calls this script TWICE with different RUNTYPE:
    #   - NOWCAST:  TIME_START=time_hotstart, TIME_END=time_nowcastend
    #   - FORECAST: TIME_START=time_nowcastend, TIME_END=time_forecastend
    # Each call builds its own tmp.out with different EXIST_CYCLE criteria.
    #
    # We replicate this by building separate file lists for each period.
    # ==========================================================================

    log_info "Using Fortran file search (nos_ofs_met_file_search) for HRRR..."
    log_info "  Matching COMF SFLUX file selection exactly"

    # Create working directory for file search
    local SEARCH_DIR="${TEMP_DIR}/file_search"
    mkdir -p $SEARCH_DIR
    cd $SEARCH_DIR

    # Determine nowcast end time
    local NOWCASTEND=${time_nowcastend:-${PDY}${cyc}}
    log_info "  TIME_START:  $TIME_START"
    log_info "  NOWCASTEND:  $NOWCASTEND"
    log_info "  TIME_END:    $TIME_END"

    # Check Fortran executable
    if [ ! -x "$MET_FILE_SEARCH" ]; then
        log_warn "Fortran executable not found: $MET_FILE_SEARCH"
        cd - > /dev/null
        return 1
    fi

    # ==========================================================================
    # Helper: Build HRRR file list matching COMF logic
    # Args: $1=RUNTYPE (nowcast|forecast), $2=search_start, $3=search_end
    #        $4=output_file
    # ==========================================================================
    _build_comf_hrrr_filelist() {
        local RUNTYPE_LOCAL=$1
        local SEARCH_TIME_START=$2
        local SEARCH_TIME_END=$3
        local OUTPUT_LIST=$4

        rm -f $OUTPUT_LIST

        # COMF starts search 15h before TIME_START (3h buffer + 12h lookback)
        local SEARCH_START=$($NDATE -15 $SEARCH_TIME_START)
        local SEARCH_DATE=$(echo $SEARCH_START | cut -c1-8)
        local END_DATE=$(echo $SEARCH_TIME_END | cut -c1-8)

        local EXIST_CYCLE=""
        local EXIST_DATE=""

        # Phase A: Detection loop (matches COMF lines 255-278)
        # Loop through dates and cycles, checking f01 existence
        local TMPDATE=$SEARCH_DATE
        while [ "$TMPDATE" -le "$END_DATE" ]; do
            local N=0
            while (( N < 24 )); do
                local CYCLE=$(printf "%02d" $N)
                local TMPFILE="${COMIN}/hrrr.${TMPDATE}/conus/hrrr.t${CYCLE}z.wrfsfcf01.grib2"

                if [ -s "${TMPFILE}.idx" ] || [ -s "$TMPFILE" ]; then
                    echo "$TMPFILE" >> $OUTPUT_LIST

                    if [ "$RUNTYPE_LOCAL" == "nowcast" ]; then
                        # Nowcast: any cycle with f01 qualifies
                        EXIST_CYCLE=$CYCLE
                        EXIST_DATE=$TMPDATE
                    elif [ "$RUNTYPE_LOCAL" == "forecast" ]; then
                        # Forecast: require f48 to also exist
                        local TMPFILE48="${COMIN}/hrrr.${TMPDATE}/conus/hrrr.t${CYCLE}z.wrfsfcf48.grib2"
                        if [ -s "${TMPFILE48}.idx" ] || [ -s "$TMPFILE48" ]; then
                            EXIST_CYCLE=$CYCLE
                            EXIST_DATE=$TMPDATE
                        fi
                    fi
                fi
                (( N = N + 1 ))
            done
            TMPDATE=$($NDATE 24 ${TMPDATE}00 | cut -c1-8)
        done

        if [ -z "$EXIST_CYCLE" ]; then
            log_warn "  No EXIST_CYCLE found for $RUNTYPE_LOCAL"
            return 1
        fi

        log_info "  EXIST_CYCLE ($RUNTYPE_LOCAL): ${EXIST_DATE} t${EXIST_CYCLE}z"

        # Phase B: Collection loop (matches COMF lines 300-326)
        # Add forecast hours from EXIST_CYCLE only
        if [ "$RUNTYPE_LOCAL" == "nowcast" ]; then
            # Nowcast: f01-f22 from EXIST_CYCLE
            local N=1
            while (( N < 23 )); do
                local FF=$(printf "%02d" $N)
                local TMPFILE="${COMIN}/hrrr.${EXIST_DATE}/conus/hrrr.t${EXIST_CYCLE}z.wrfsfcf${FF}.grib2"
                if [ -s "${TMPFILE}.idx" ] || [ -s "$TMPFILE" ]; then
                    echo "$TMPFILE" >> $OUTPUT_LIST
                fi
                (( N = N + 1 ))
            done
        elif [ "$RUNTYPE_LOCAL" == "forecast" ]; then
            # Forecast: f01-f48 from EXIST_CYCLE
            local N=1
            while (( N < 49 )); do
                local FF=$(printf "%02d" $N)
                local TMPFILE="${COMIN}/hrrr.${EXIST_DATE}/conus/hrrr.t${EXIST_CYCLE}z.wrfsfcf${FF}.grib2"
                if [ -s "${TMPFILE}.idx" ] || [ -s "$TMPFILE" ]; then
                    echo "$TMPFILE" >> $OUTPUT_LIST
                fi
                (( N = N + 1 ))
            done
        fi

        local NFILES=$(wc -l < $OUTPUT_LIST 2>/dev/null || echo "0")
        log_info "  $RUNTYPE_LOCAL file list: $NFILES entries"
        return 0
    }

    # ==========================================================================
    # Step 1: Build NOWCAST file list (matching COMF NOWCAST call)
    # COMF: TIME_START=time_hotstart, TIME_END=time_nowcastend, RUNTYPE=nowcast
    # ==========================================================================
    log_info "  [1/2] Building NOWCAST file list..."
    _build_comf_hrrr_filelist "nowcast" "$TIME_START" "$NOWCASTEND" "tmp_nowcast.out"

    # ==========================================================================
    # Step 2: Build FORECAST file list (matching COMF FORECAST call)
    # COMF: TIME_START=time_nowcastend, TIME_END=time_forecastend, RUNTYPE=forecast
    # ==========================================================================
    log_info "  [2/2] Building FORECAST file list..."
    _build_comf_hrrr_filelist "forecast" "$NOWCASTEND" "$TIME_END" "tmp_forecast.out"

    # ==========================================================================
    # Step 3: Run Fortran for NOWCAST period
    # COMF control file format:
    #   CURRENTTIME (TIME_START_TMP or adjusted)
    #   time_nowcastend
    #   TIME_END
    #   tmp.out
    #   MET_FILE
    # For nowcast, TIME_END = time_nowcastend
    # ==========================================================================
    log_info "  Running Fortran for NOWCAST ($TIME_START to $NOWCASTEND)..."

    # Match COMF's start time: TIME_START_TMP = TIME_START - 3h
    local NOWCAST_START=$($NDATE -3 $TIME_START)
    if [ "$NOWCAST_START" -gt "$NOWCASTEND" ]; then
        NOWCAST_START=$($NDATE -24 $NOWCASTEND)
    fi

    cat > Fortran_nowcast.ctl << EOF
$NOWCAST_START
$NOWCASTEND
$NOWCASTEND
tmp_nowcast.out
HRRR_FILE_nowcast.dat
EOF

    $MET_FILE_SEARCH < Fortran_nowcast.ctl > Fortran_nowcast.log 2>&1

    if grep -q "COMPLETED SUCCESSFULLY" Fortran_nowcast.log; then
        local NOWCAST_FILES=$(grep -c "^/" HRRR_FILE_nowcast.dat 2>/dev/null || echo "0")
        log_info "    Nowcast: Selected $NOWCAST_FILES files"
    else
        log_warn "    Nowcast file search failed - check Fortran_nowcast.log"
    fi

    # ==========================================================================
    # Step 4: Run Fortran for FORECAST period
    # COMF: CURRENTTIME = TIME_START_TMP (= time_nowcastend - 3h)
    # ==========================================================================
    log_info "  Running Fortran for FORECAST ($NOWCASTEND to $TIME_END)..."

    local FORECAST_START=$($NDATE -3 $NOWCASTEND)
    if [ "$FORECAST_START" -gt "$NOWCASTEND" ]; then
        FORECAST_START=$($NDATE -24 $NOWCASTEND)
    fi

    cat > Fortran_forecast.ctl << EOF
$FORECAST_START
$NOWCASTEND
$TIME_END
tmp_forecast.out
HRRR_FILE_forecast.dat
EOF

    $MET_FILE_SEARCH < Fortran_forecast.ctl > Fortran_forecast.log 2>&1

    if grep -q "COMPLETED SUCCESSFULLY" Fortran_forecast.log; then
        local FORECAST_FILES=$(grep -c "^/" HRRR_FILE_forecast.dat 2>/dev/null || echo "0")
        log_info "    Forecast: Selected $FORECAST_FILES files"
    else
        log_warn "    Forecast file search failed - check Fortran_forecast.log"
    fi

    # ==========================================================================
    # Step 5: Combine nowcast and forecast files (skip first forecast entry
    # since NOWCASTEND is included in both)
    # ==========================================================================
    log_info "  Combining nowcast + forecast files..."

    local MET_FILE="HRRR_FILE_DATM.dat"
    rm -f $MET_FILE

    # Add all nowcast files
    if [ -s HRRR_FILE_nowcast.dat ]; then
        cat HRRR_FILE_nowcast.dat >> $MET_FILE
    fi

    # Add forecast files (skip first 2 lines which duplicate NOWCASTEND hour)
    if [ -s HRRR_FILE_forecast.dat ]; then
        tail -n +3 HRRR_FILE_forecast.dat >> $MET_FILE
    fi

    # Step 6: Verify and set output
    if [ -s "$MET_FILE" ]; then
        HRRR_FILE_LIST="$SEARCH_DIR/$MET_FILE"
        local NSELECTED=$(grep -c "^/" "$MET_FILE" 2>/dev/null || echo "0")
        log_info "  Total: Selected $NSELECTED files for DATM"

        # Log the selected files in verbose mode
        if [ "$VERBOSE" -ge 2 ]; then
            log_debug "  Selected files:"
            while IFS= read -r line; do
                if [[ "$line" == /* ]]; then
                    log_debug "    $line"
                fi
            done < "$MET_FILE"
        fi

        # Save file lists for debugging (matches COMF's met_files_existed_*.dat)
        cp -p tmp_nowcast.out $SEARCH_DIR/met_files_existed_NOWCAST_HRRR.dat 2>/dev/null
        cp -p tmp_forecast.out $SEARCH_DIR/met_files_existed_FORECAST_HRRR.dat 2>/dev/null
    else
        log_warn "  No output file generated"
        cd - > /dev/null
        return 1
    fi

    cd - > /dev/null
    return 0
}

# =============================================================================
# Function: Get HRRR file for a valid time from Fortran-selected list
# =============================================================================
get_hrrr_file_from_list() {
    local VALID_TIME=$1

    if [ -z "$HRRR_FILE_LIST" ] || [ ! -s "$HRRR_FILE_LIST" ]; then
        echo ""
        return 1
    fi

    # Parse the Fortran output file
    local VALID_DATE=$(echo $VALID_TIME | cut -c1-8)
    local VALID_HH=$(echo $VALID_TIME | cut -c9-10)

    local FOUND_FILE=""
    local PREV_LINE=""

    while IFS= read -r line; do
        if [[ "$line" == /* ]]; then
            PREV_LINE="$line"
        else
            # Parse date line: YYYY MM DD CYC FHR
            local FILE_YEAR=$(echo $line | awk '{print $1}')
            local FILE_MON=$(echo $line | awk '{print $2}')
            local FILE_DAY=$(echo $line | awk '{print $3}')
            local FILE_CYC=$(echo $line | awk '{print $4}')
            local FILE_FHR=$(echo $line | awk '{print $5}')

            # Calculate valid time for this file
            local FILE_DATE="${FILE_YEAR}$(printf '%02d' $FILE_MON)$(printf '%02d' $FILE_DAY)"
            local FILE_VALID_HH=$((10#$FILE_CYC + 10#$FILE_FHR))

            # Handle day rollover
            while [ $FILE_VALID_HH -ge 24 ]; do
                FILE_VALID_HH=$((FILE_VALID_HH - 24))
                FILE_DATE=$($NDATE 24 ${FILE_DATE}00 | cut -c1-8)
            done

            local FILE_VALID_TIME="${FILE_DATE}$(printf '%02d' $FILE_VALID_HH)"

            if [ "$FILE_VALID_TIME" == "$VALID_TIME" ]; then
                FOUND_FILE="$PREV_LINE"
                FILES_USED+=("$VALID_TIME|${FILE_CYC}z|f$(printf '%02d' $FILE_FHR)|$(basename $PREV_LINE)")
                break
            fi
        fi
    done < "$HRRR_FILE_LIST"

    echo "$FOUND_FILE"
}

# =============================================================================
# Function: Find HRRR file (wrapper - tries Fortran first)
# =============================================================================
HRRR_FORTRAN_INITIALIZED=0

find_hrrr_file() {
    local VALID_TIME=$1

    # Initialize Fortran file list on first call
    if [ "$HRRR_FORTRAN_INITIALIZED" -eq 0 ]; then
        find_hrrr_files_fortran
        HRRR_FORTRAN_INITIALIZED=1
    fi

    # Try to get file from Fortran-selected list
    local GRIB2_FILE=$(get_hrrr_file_from_list $VALID_TIME)

    if [ -n "$GRIB2_FILE" ] && [ -s "$GRIB2_FILE" ]; then
        log_debug "$VALID_TIME -> $(basename $GRIB2_FILE)"
        echo "$GRIB2_FILE"
        return 0
    fi

    log_warn "$VALID_TIME -> No HRRR file found in Fortran selection"
    echo ""
    return 1
}

# =============================================================================
# Function: Print summary of files used
# =============================================================================
print_files_summary() {
    log_info ""
    log_info "============================================"
    log_info "SUMMARY: GRIB2 FILES USED (Fortran selection)"
    log_info "============================================"
    log_info ""
    log_info "Valid Time       | Cycle | FHR  | File"
    log_info "-----------------|-------|------|----------------------------------"

    for entry in "${FILES_USED[@]}"; do
        local vtime=$(echo $entry | cut -d'|' -f1)
        local cycle=$(echo $entry | cut -d'|' -f2)
        local fhr=$(echo $entry | cut -d'|' -f3)
        local fname=$(echo $entry | cut -d'|' -f4)
        log_info "$vtime | $cycle  | $fhr  | $fname"
    done
    log_info "============================================"
    log_info "Total files: ${#FILES_USED[@]}"
    log_info ""
}

# =============================================================================
# Step 1: Find and extract variables for each timestep
# =============================================================================
echo ""
echo "Step 1: Finding GRIB2 files for time range..."
echo "============================================"

FILE_COUNT=0
MISSING_COUNT=0
CURRENT_TIME=$TIME_START
FILE_LIST=""

while [ "$CURRENT_TIME" -le "$TIME_END" ]; do
    TIME_STR=$CURRENT_TIME
    NC_FILE="${TEMP_DIR}/${DBASE_LOWER}_${TIME_STR}.nc"

    # Find the appropriate GRIB2 file
    if [ "$DBASE_UPPER" == "GFS" ] || [ "$DBASE_UPPER" == "GFS25" ]; then
        GRIB2_FILE=$(find_gfs_file $CURRENT_TIME)
    else
        GRIB2_FILE=$(find_hrrr_file $CURRENT_TIME)
    fi

    if [ -n "$GRIB2_FILE" ] && [ -s "$GRIB2_FILE" ]; then
        echo "Processing ${TIME_STR}: $GRIB2_FILE"

        $WGRIB2 $GRIB2_FILE \
            -match "$MATCH_PATTERN" \
            -netcdf $NC_FILE

        if [ -s "$NC_FILE" ]; then
            FILE_COUNT=$((FILE_COUNT + 1))
            FILE_LIST="$FILE_LIST $NC_FILE"
        else
            echo "WARNING: Failed to extract data for $TIME_STR"
            MISSING_COUNT=$((MISSING_COUNT + 1))
        fi
    else
        echo "WARNING: No file found for valid time $TIME_STR"
        MISSING_COUNT=$((MISSING_COUNT + 1))
    fi

    # Advance to next timestep
    CURRENT_TIME=$($NDATE $INTERVAL $CURRENT_TIME)
done

echo ""
echo "Extracted $FILE_COUNT files, $MISSING_COUNT missing"

if [ $FILE_COUNT -eq 0 ]; then
    echo "ERROR: No files extracted. Check input paths."
    rm -rf $TEMP_DIR
    exit 1
fi

# =============================================================================
# Step 2: Concatenate files along time dimension
# =============================================================================
echo ""
echo "Step 2: Concatenating files..."
echo "============================================"

# Sort files by name (which sorts by time due to naming convention)
NC_FILES=$(ls -1 ${TEMP_DIR}/${DBASE_LOWER}_*.nc 2>/dev/null | sort)
NUM_FILES=$(echo "$NC_FILES" | wc -l)
echo "Found $NUM_FILES NetCDF files to concatenate"

if [ -z "$NC_FILES" ]; then
    echo "ERROR: No NetCDF files found to concatenate"
    rm -rf $TEMP_DIR
    exit 1
fi

# Use NCO ncrcat for concatenation
if command -v ncrcat &> /dev/null; then
    echo "Using NCO ncrcat for concatenation..."
    ncrcat -O $NC_FILES ${OUTPUT_DIR}/${DBASE_LOWER}_forcing_raw.nc
    CONCAT_STATUS=$?
else
    echo "ERROR: ncrcat not found. Please load NCO module."
    rm -rf $TEMP_DIR
    exit 1
fi

if [ $CONCAT_STATUS -ne 0 ] || [ ! -s ${OUTPUT_DIR}/${DBASE_LOWER}_forcing_raw.nc ]; then
    echo "ERROR: Concatenation failed"
    rm -rf $TEMP_DIR
    exit 1
fi

echo "Created: ${OUTPUT_DIR}/${DBASE_LOWER}_forcing_raw.nc"

# =============================================================================
# Step 3: Add CF-compliance and CDEPS-compatible time attributes
# =============================================================================
echo ""
echo "Step 3: Adding CF-compliance and CDEPS time attributes..."
echo "============================================"

cp ${OUTPUT_DIR}/${DBASE_LOWER}_forcing_raw.nc $OUTPUT_FILE

# Add global attributes
if command -v ncatted &> /dev/null; then
    ncatted -h -a Conventions,global,o,c,"CF-1.6" $OUTPUT_FILE
    ncatted -h -a title,global,o,c,"${DBASE_UPPER} forcing data for UFS-Coastal DATM" $OUTPUT_FILE
    ncatted -h -a source,global,o,c,"NCEP ${DBASE_UPPER}" $OUTPUT_FILE
    ncatted -h -a institution,global,o,c,"NOAA/NOS/OCS" $OUTPUT_FILE
    ncatted -h -a history,global,o,c,"Created by nos_ofs_create_datm_forcing.sh on $(date)" $OUTPUT_FILE

    # Add coordinate attributes
    ncatted -h -a units,longitude,o,c,"degrees_east" $OUTPUT_FILE
    ncatted -h -a axis,longitude,o,c,"X" $OUTPUT_FILE
    ncatted -h -a standard_name,longitude,o,c,"longitude" $OUTPUT_FILE

    ncatted -h -a units,latitude,o,c,"degrees_north" $OUTPUT_FILE
    ncatted -h -a axis,latitude,o,c,"Y" $OUTPUT_FILE
    ncatted -h -a standard_name,latitude,o,c,"latitude" $OUTPUT_FILE

    ncatted -h -a axis,time,o,c,"T" $OUTPUT_FILE

    # =========================================================================
    # CRITICAL: CDEPS/ESMF-compatible time attributes
    # Without these, shr_stream_findBounds will fail with:
    #   "ERROR: limit on and rDateIn lt rDatelvd"
    # CDEPS requires epoch-based time units and calendar attribute for proper
    # date parsing by the ESMF time manager.
    # =========================================================================
    echo "Adding CDEPS-compatible time attributes..."

    # Set time units to epoch format (required by CDEPS)
    ncatted -O -a units,time,o,c,"seconds since 1970-01-01 00:00:00" $OUTPUT_FILE

    # Add calendar attribute (required by CDEPS/ESMF time manager)
    ncatted -O -a calendar,time,o,c,"standard" $OUTPUT_FILE

    # Remove potentially conflicting reference time attributes
    ncatted -O -a reference_time,time,d,, $OUTPUT_FILE 2>/dev/null || true
    ncatted -O -a reference_date,time,d,, $OUTPUT_FILE 2>/dev/null || true
    ncatted -O -a reference_time_type,time,d,, $OUTPUT_FILE 2>/dev/null || true
    ncatted -O -a reference_time_description,time,d,, $OUTPUT_FILE 2>/dev/null || true

    echo "CDEPS time attributes added successfully"
fi

echo "Created: $OUTPUT_FILE"

# =============================================================================
# Step 4: Verify output
# =============================================================================
echo ""
echo "Step 4: Verifying output..."
echo "============================================"

if command -v ncdump &> /dev/null; then
    TIME_STEPS=$(ncdump -h $OUTPUT_FILE | grep "time = " | head -1 | sed 's/.*time = \([0-9]*\).*/\1/')
fi
FILE_SIZE=$(ls -lh $OUTPUT_FILE | awk '{print $5}')

echo "Output file: $OUTPUT_FILE"
echo "File size:   $FILE_SIZE"
echo "Time steps:  $TIME_STEPS"
echo ""

if command -v ncdump &> /dev/null; then
    echo "Variables:"
    ncdump -h $OUTPUT_FILE | grep -E "^\s+(float|double)" | head -10
fi

# =============================================================================
# Cleanup - Preserve temp directory for debugging
# =============================================================================
echo ""
echo "Preserving work directory for debugging..."

# Remove intermediate raw file
rm -f ${OUTPUT_DIR}/${DBASE_LOWER}_forcing_raw.nc

# Move temp directory to output directory (renamed for clarity)
WORK_DIR_DEST="${OUTPUT_DIR}/datm_work_${PDY}${cyc}"
if [ -d "$WORK_DIR_DEST" ]; then
    rm -rf "$WORK_DIR_DEST"
fi
mv $TEMP_DIR $WORK_DIR_DEST
echo "Work directory saved to: $WORK_DIR_DEST"
echo ""
echo "Contents of work directory:"
ls -la $WORK_DIR_DEST/ 2>/dev/null | head -20
if [ -d "$WORK_DIR_DEST/file_search" ]; then
    echo ""
    echo "File search artifacts:"
    ls -la $WORK_DIR_DEST/file_search/ 2>/dev/null
fi

# Print summary of files used (if HRRR and verbose mode)
if [ "$DBASE_UPPER" == "HRRR" ] && [ "$VERBOSE" -ge 1 ]; then
    print_files_summary
fi

echo ""
echo "============================================"
echo "DATM Forcing Generation COMPLETED"
echo "============================================"
echo "Output: $OUTPUT_FILE"
echo "Time range: $TIME_START to $TIME_END"
echo "Time steps: $TIME_STEPS"
if [ "$DBASE_UPPER" == "HRRR" ]; then
    echo "File selection: nos_ofs_met_file_search (Fortran)"
    echo "Work directory: $WORK_DIR_DEST"
fi
echo "============================================"

# Save file list to log if LOG_FILE specified
if [ -n "$LOG_FILE" ] && [ "$DBASE_UPPER" == "HRRR" ]; then
    echo "" >> "$LOG_FILE"
    echo "FILES_USED:" >> "$LOG_FILE"
    for entry in "${FILES_USED[@]}"; do
        echo "  $entry" >> "$LOG_FILE"
    done
fi

exit 0
