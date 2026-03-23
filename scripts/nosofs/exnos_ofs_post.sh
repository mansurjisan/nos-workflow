#!/bin/bash
set -x

########################################
# COMF SCHISM Post-Processing
#
# Generates CO-OPS standard station timeseries NetCDF from staout files:
#   {prefix}.t{cyc}z.{PDY}.stations.nowcast.nc
#   {prefix}.t{cyc}z.{PDY}.stations.forecast.nc
#
# Inputs (from COMOUT, produced by nowcast/forecast jobs):
#   ${RUN}.${cycle}.restart_outputs/staout_{1..9}   (nowcast)
#   ${RUN}.${cycle}.forecast_outputs/staout_{1..9}   (forecast)
#
# Uses schism_combine_outputs.py to convert staout text → NetCDF.
########################################

echo "============================================="
echo "Starting COMF SCHISM post-processing"
echo "  OFS:  ${OFS}"
echo "  PDY:  ${PDY}"
echo "  cyc:  ${cyc}"
echo "  COMOUT: ${COMOUT}"
echo "============================================="

export err=0

COMBINE_SCRIPT="${HOMEnos}/ush/nosofs/schism_combine_outputs.py"
if [ ! -f "$COMBINE_SCRIPT" ]; then
    echo "FATAL: schism_combine_outputs.py not found at $COMBINE_SCRIPT"
    export err=1
    exit $err
fi

# Station file for lat/lon extraction
STA_IN="${FIXofs}/${PREFIXNOS}.station.in"
if [ ! -f "$STA_IN" ]; then
    STA_IN="${FIXofs}/${STA_OUT_CTL:-${PREFIXNOS}.station.in}"
fi
if [ ! -f "$STA_IN" ]; then
    echo "FATAL: station.in not found"
    export err=1
    exit $err
fi

# Compute nowcast base time (cyc - LEN_NOWCAST hours)
NC_HOUR=$(printf '%02d' $(( ${cyc#0} - ${LEN_NOWCAST:-6} )))
# Handle day rollback if needed
if [ ${NC_HOUR#0} -lt 0 ]; then
    NC_HOUR=$(printf '%02d' $(( ${NC_HOUR#0} + 24 )))
    # PDY would need adjustment too for cross-midnight — skip for now
fi

########################################
# Process each phase (nowcast, forecast)
########################################
for phase in nowcast forecast; do

    echo ""
    echo "--- Processing $phase ---"

    # Locate staout files
    if [ "$phase" = "nowcast" ]; then
        STAOUT_DIR="${COMOUT}/${RUN}.${cycle}.restart_outputs"
        MODE_FLAG="n"
        TIMESTART="${PDY}${NC_HOUR}"
    else
        STAOUT_DIR="${COMOUT}/${RUN}.${cycle}.forecast_outputs"
        MODE_FLAG="f"
        TIMESTART="${PDY}${cyc}"
    fi

    if [ ! -f "$STAOUT_DIR/staout_1" ]; then
        echo "WARNING: $STAOUT_DIR/staout_1 not found, skipping $phase"
        continue
    fi

    # Set up working directory
    WORK_POST="$DATA/post_${phase}"
    mkdir -p "$WORK_POST"

    # Create control file
    cat > "$WORK_POST/schism_standard_output.ctl" << EOF
${PREFIXNOS}
${cyc}
${PDY}
${MODE_FLAG}
${TIMESTART}
EOF

    # Create station.lat.lon
    awk 'NR>2 && NF>=3 {print NR-2, $2, $3}' "$STA_IN" \
        > "$WORK_POST/${PREFIXNOS}.station.lat.lon"

    # Symlink staout files
    for f in staout_1 staout_2 staout_3 staout_4 staout_5 \
             staout_6 staout_7 staout_8 staout_9; do
        [ -f "$STAOUT_DIR/$f" ] && ln -sf "$STAOUT_DIR/$f" "$WORK_POST/$f"
    done

    # Run combine script
    echo "Running schism_combine_outputs.py for $phase ..."
    (cd "$WORK_POST" && LD_PRELOAD= python3 "$COMBINE_SCRIPT") >> $pgmout 2>&1
    rc=$?

    if [ $rc -ne 0 ]; then
        echo "WARNING: schism_combine_outputs.py failed for $phase (rc=$rc)"
        continue
    fi

    # Copy station NetCDF to COMOUT
    STA_NC="$WORK_POST/${PREFIXNOS}.t${cyc}z.${PDY}.stations.${phase}.nc"
    if [ -f "$STA_NC" ]; then
        cp -p "$STA_NC" "${COMOUT}/"
        echo "Created: $(basename $STA_NC)"
    else
        echo "WARNING: Expected station NetCDF not found: $STA_NC"
    fi

done

echo ""
echo "============================================="
echo "COMF SCHISM post-processing completed"
echo "============================================="

exit $err
