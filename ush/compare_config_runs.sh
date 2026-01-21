#!/bin/bash
###############################################################################
# compare_config_runs.sh
#
# Compare CTL-based vs YAML-based NOS OFS prep runs
# Validates that YAML configuration produces identical results to legacy .ctl
#
# Usage:
#   ./compare_config_runs.sh <ctl_log> <yaml_log>
#   ./compare_config_runs.sh secofs_prep_00.err secofs_prep_00.err.91462567
#
# Author: NOS/CO-OPS
###############################################################################

set -u

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check arguments
if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <ctl_log_file> <yaml_log_file> [output_dir]"
    echo ""
    echo "Example:"
    echo "  $0 secofs_prep_00.err secofs_prep_00.err.91462567"
    echo "  $0 /path/to/ctl.log /path/to/yaml.log /tmp/comparison"
    exit 1
fi

CTL_LOG="$1"
YAML_LOG="$2"
OUTPUT_DIR="${3:-./config_comparison}"

# Validate input files
if [[ ! -f "$CTL_LOG" ]]; then
    echo -e "${RED}ERROR: CTL log file not found: $CTL_LOG${NC}"
    exit 1
fi

if [[ ! -f "$YAML_LOG" ]]; then
    echo -e "${RED}ERROR: YAML log file not found: $YAML_LOG${NC}"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "=============================================="
echo "NOS OFS Configuration Comparison"
echo "=============================================="
echo "CTL Log:  $CTL_LOG"
echo "YAML Log: $YAML_LOG"
echo "Output:   $OUTPUT_DIR"
echo "=============================================="
echo ""

###############################################################################
# 1. Extract all exported environment variables
###############################################################################
echo -e "${BLUE}[1/5] Extracting environment variables...${NC}"

# Key variables to compare (critical for model execution)
KEY_VARS=(
    # Domain bounds
    "MINLON" "MAXLON" "MINLAT" "MAXLAT"
    # Grid dimensions
    "np_global" "ne_global" "ns_global" "nvrt" "KBm"
    # Time settings
    "cyc" "PDY" "time_nowcastend" "time_forecastend" "time_hotstart"
    "LEN_NOWCAST" "LEN_FORECAST" "DELT_MODEL"
    # Forcing sources
    "DBASE_MET_NOW" "DBASE_MET_FOR" "DBASE_MET_NOW2" "DBASE_MET_FOR2"
    "DBASE_WL_NOW" "DBASE_WL_FOR" "DBASE_TS_NOW" "DBASE_TS_FOR"
    "MET_NUM"
    # Control files
    "RIVER_CTL_FILE" "RIVER_CLIM_FILE" "OBC_CTL_FILE" "OBC_CLIM_FILE"
    "HC_FILE_OBC" "HC_FILE_OFS" "HC_FILE_NWLON"
    "RUNTIME_CTL" "RUNTIME_MET_CTL"
    # Grid files
    "GRIDFILE" "GRIDFILE_LL" "VGRID_CTL" "STA_OUT_CTL"
    # Output settings
    "NSTA" "NSTATION" "NHIS" "NAVG" "NRST" "NFLT"
    # Model settings
    "CREATE_TIDEFORCING" "IGRD_MET" "IGRD_OBC"
    "PREFIXNOS" "RUN" "OCEAN_MODEL"
    # Physics
    "NWS_VALUE" "STEP_NU_VALUE" "MIN_DEPTH"
    # Resources
    "TOTAL_TASKS" "NPROCS"
)

# Build grep pattern for key variables
KEY_PATTERN=$(IFS="|"; echo "${KEY_VARS[*]}")

# Extract exports from CTL log
grep -E "^\s*\+?\s*export\s+" "$CTL_LOG" | \
    sed 's/^[[:space:]]*+*[[:space:]]*export[[:space:]]*//' | \
    sort -u > "$OUTPUT_DIR/ctl_all_exports.txt"

# Extract exports from YAML log
grep -E "^\s*\+?\s*export\s+" "$YAML_LOG" | \
    sed 's/^[[:space:]]*+*[[:space:]]*export[[:space:]]*//' | \
    sort -u > "$OUTPUT_DIR/yaml_all_exports.txt"

# Extract only key variables
grep -E "^($KEY_PATTERN)=" "$OUTPUT_DIR/ctl_all_exports.txt" | sort > "$OUTPUT_DIR/ctl_key_vars.txt"
grep -E "^($KEY_PATTERN)=" "$OUTPUT_DIR/yaml_all_exports.txt" | sort > "$OUTPUT_DIR/yaml_key_vars.txt"

echo "  Extracted $(wc -l < "$OUTPUT_DIR/ctl_all_exports.txt") total exports from CTL"
echo "  Extracted $(wc -l < "$OUTPUT_DIR/yaml_all_exports.txt") total exports from YAML"
echo "  Filtered to $(wc -l < "$OUTPUT_DIR/ctl_key_vars.txt") key variables"
echo ""

###############################################################################
# 2. Compare key variables
###############################################################################
echo -e "${BLUE}[2/5] Comparing key variables...${NC}"

# Create comparison report
REPORT="$OUTPUT_DIR/comparison_report.txt"
echo "NOS OFS Configuration Comparison Report" > "$REPORT"
echo "Generated: $(date)" >> "$REPORT"
echo "CTL Log: $CTL_LOG" >> "$REPORT"
echo "YAML Log: $YAML_LOG" >> "$REPORT"
echo "========================================" >> "$REPORT"
echo "" >> "$REPORT"

# Track differences
DIFF_COUNT=0
MATCH_COUNT=0
MISSING_CTL=0
MISSING_YAML=0

echo "KEY VARIABLE COMPARISON" >> "$REPORT"
echo "-----------------------" >> "$REPORT"

for var in "${KEY_VARS[@]}"; do
    ctl_val=$(grep "^${var}=" "$OUTPUT_DIR/ctl_key_vars.txt" 2>/dev/null | head -1 | cut -d= -f2-)
    yaml_val=$(grep "^${var}=" "$OUTPUT_DIR/yaml_key_vars.txt" 2>/dev/null | head -1 | cut -d= -f2-)

    if [[ -z "$ctl_val" && -z "$yaml_val" ]]; then
        # Both missing - skip
        continue
    elif [[ -z "$ctl_val" ]]; then
        echo -e "${YELLOW}  [MISSING CTL] $var${NC}"
        echo "[MISSING CTL] $var = $yaml_val (YAML only)" >> "$REPORT"
        ((MISSING_CTL++))
    elif [[ -z "$yaml_val" ]]; then
        echo -e "${YELLOW}  [MISSING YAML] $var${NC}"
        echo "[MISSING YAML] $var = $ctl_val (CTL only)" >> "$REPORT"
        ((MISSING_YAML++))
    elif [[ "$ctl_val" == "$yaml_val" ]]; then
        echo -e "${GREEN}  [MATCH] $var = $ctl_val${NC}"
        echo "[MATCH] $var = $ctl_val" >> "$REPORT"
        ((MATCH_COUNT++))
    else
        echo -e "${RED}  [DIFF] $var${NC}"
        echo -e "${RED}         CTL:  $ctl_val${NC}"
        echo -e "${RED}         YAML: $yaml_val${NC}"
        echo "[DIFF] $var" >> "$REPORT"
        echo "       CTL:  $ctl_val" >> "$REPORT"
        echo "       YAML: $yaml_val" >> "$REPORT"
        ((DIFF_COUNT++))
    fi
done

echo "" >> "$REPORT"

###############################################################################
# 3. Full diff of all exports
###############################################################################
echo ""
echo -e "${BLUE}[3/5] Running full diff...${NC}"

diff "$OUTPUT_DIR/ctl_key_vars.txt" "$OUTPUT_DIR/yaml_key_vars.txt" > "$OUTPUT_DIR/key_vars_diff.txt" 2>&1
if [[ -s "$OUTPUT_DIR/key_vars_diff.txt" ]]; then
    echo "  Differences found - see $OUTPUT_DIR/key_vars_diff.txt"
else
    echo "  No differences in key variables"
fi

diff "$OUTPUT_DIR/ctl_all_exports.txt" "$OUTPUT_DIR/yaml_all_exports.txt" > "$OUTPUT_DIR/all_exports_diff.txt" 2>&1
if [[ -s "$OUTPUT_DIR/all_exports_diff.txt" ]]; then
    echo "  Full export diff available in $OUTPUT_DIR/all_exports_diff.txt"
fi

###############################################################################
# 4. Check for errors in logs
###############################################################################
echo ""
echo -e "${BLUE}[4/5] Checking for errors...${NC}"

echo "" >> "$REPORT"
echo "ERROR CHECK" >> "$REPORT"
echo "-----------" >> "$REPORT"

# Check CTL log for errors
CTL_ERRORS=$(grep -i "FATAL\|ERROR\|FAILED" "$CTL_LOG" | grep -v "postmsg" | head -5)
if [[ -n "$CTL_ERRORS" ]]; then
    echo -e "${RED}  CTL log has errors:${NC}"
    echo "$CTL_ERRORS" | head -3
    echo "CTL Errors:" >> "$REPORT"
    echo "$CTL_ERRORS" >> "$REPORT"
else
    echo -e "${GREEN}  CTL log: No fatal errors${NC}"
    echo "CTL: No fatal errors" >> "$REPORT"
fi

# Check YAML log for errors
YAML_ERRORS=$(grep -i "FATAL\|ERROR\|FAILED" "$YAML_LOG" | grep -v "postmsg" | head -5)
if [[ -n "$YAML_ERRORS" ]]; then
    echo -e "${RED}  YAML log has errors:${NC}"
    echo "$YAML_ERRORS" | head -3
    echo "YAML Errors:" >> "$REPORT"
    echo "$YAML_ERRORS" >> "$REPORT"
else
    echo -e "${GREEN}  YAML log: No fatal errors${NC}"
    echo "YAML: No fatal errors" >> "$REPORT"
fi

###############################################################################
# 5. Check config source
###############################################################################
echo ""
echo -e "${BLUE}[5/5] Verifying config sources...${NC}"

echo "" >> "$REPORT"
echo "CONFIG SOURCE" >> "$REPORT"
echo "-------------" >> "$REPORT"

CTL_SOURCE=$(grep "CONFIG_SOURCE=" "$CTL_LOG" | tail -1)
YAML_SOURCE=$(grep "CONFIG_SOURCE=" "$YAML_LOG" | tail -1)

echo "  CTL run:  $CTL_SOURCE"
echo "  YAML run: $YAML_SOURCE"
echo "CTL run: $CTL_SOURCE" >> "$REPORT"
echo "YAML run: $YAML_SOURCE" >> "$REPORT"

###############################################################################
# Summary
###############################################################################
echo ""
echo "=============================================="
echo -e "${BLUE}SUMMARY${NC}"
echo "=============================================="
echo -e "  Matching variables:    ${GREEN}$MATCH_COUNT${NC}"
echo -e "  Different variables:   ${RED}$DIFF_COUNT${NC}"
echo -e "  Missing in CTL:        ${YELLOW}$MISSING_CTL${NC}"
echo -e "  Missing in YAML:       ${YELLOW}$MISSING_YAML${NC}"
echo ""

echo "" >> "$REPORT"
echo "SUMMARY" >> "$REPORT"
echo "-------" >> "$REPORT"
echo "Matching variables:  $MATCH_COUNT" >> "$REPORT"
echo "Different variables: $DIFF_COUNT" >> "$REPORT"
echo "Missing in CTL:      $MISSING_CTL" >> "$REPORT"
echo "Missing in YAML:     $MISSING_YAML" >> "$REPORT"

if [[ $DIFF_COUNT -eq 0 && $MISSING_CTL -eq 0 && $MISSING_YAML -eq 0 ]]; then
    echo -e "${GREEN}SUCCESS: YAML configuration matches CTL!${NC}"
    echo "" >> "$REPORT"
    echo "RESULT: SUCCESS - YAML matches CTL" >> "$REPORT"
    EXIT_CODE=0
else
    echo -e "${RED}DIFFERENCES FOUND: Review $REPORT for details${NC}"
    echo "" >> "$REPORT"
    echo "RESULT: DIFFERENCES FOUND" >> "$REPORT"
    EXIT_CODE=1
fi

echo ""
echo "Output files:"
echo "  $OUTPUT_DIR/comparison_report.txt  - Full report"
echo "  $OUTPUT_DIR/key_vars_diff.txt      - Diff of key variables"
echo "  $OUTPUT_DIR/ctl_key_vars.txt       - CTL key variables"
echo "  $OUTPUT_DIR/yaml_key_vars.txt      - YAML key variables"
echo ""

exit $EXIT_CODE
