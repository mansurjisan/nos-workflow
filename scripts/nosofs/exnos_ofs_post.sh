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

########################################
# Ensemble bias correction (2D barotropic only)
#
# If BAROTROPIC=true and ensemble member outputs exist, apply
# anomaly-based bias correction using the 3D deterministic run:
#
#   WL_final(t) = WL_3d_det(t) + a_i * (WL_2d_member(t) - WL_2d_control(t))
#
# Requires:
#   - 3D deterministic station NC (from the corresponding 3D OFS COMOUT)
#   - 2D control (member_000) staout files
#   - 2D perturbed member staout files
########################################
if [ "${BAROTROPIC:-false}" = "true" ] || [ "${BAROTROPIC:-0}" = "1" ]; then

    BIAS_SCRIPT="${HOMEnos}/ush/python/nos_ofs/ensemble/ensemble_bias_correct.py"
    # 3D deterministic OFS name (e.g., secofs_2d_ufs → secofs_ufs or secofs)
    DET_OFS=${DET_OFS:-$(echo "$OFS" | sed 's/_2d_ufs/_ufs/' | sed 's/_2d//')}
    DET_COMOUT=${DET_COMOUT:-$(dirname $COMOUT)/${DET_OFS}.${PDY}}

    DET_NCAST="${DET_COMOUT}/${DET_OFS}.t${cyc}z.${PDY}.stations.nowcast.nc"
    DET_FCAST="${DET_COMOUT}/${DET_OFS}.t${cyc}z.${PDY}.stations.forecast.nc"

    ENS_DIR="${COMOUT}/ensemble/${cycle}"
    CTL_NCAST="${ENS_DIR}/member_000/${RUN}.${cycle}.restart_outputs/staout_1"
    CTL_FCAST="${ENS_DIR}/member_000/${RUN}.${cycle}.forecast_outputs/staout_1"

    # Also check the deterministic (non-ensemble) staout locations as control
    if [ ! -f "$CTL_NCAST" ]; then
        CTL_NCAST="${COMOUT}/${RUN}.${cycle}.restart_outputs/staout_1"
    fi
    if [ ! -f "$CTL_FCAST" ]; then
        CTL_FCAST="${COMOUT}/${RUN}.${cycle}.forecast_outputs/staout_1"
    fi

    if [ -f "$BIAS_SCRIPT" ] && [ -f "$DET_NCAST" ] && [ -f "$DET_FCAST" ] && \
       [ -f "$CTL_NCAST" ] && [ -f "$CTL_FCAST" ]; then

        echo ""
        echo "============================================="
        echo "Ensemble bias correction (2D → 3D anchored)"
        echo "  3D det: $DET_OFS"
        echo "  Control: member_000"
        echo "============================================="

        COEFF_FILE="${COMOUT}/bias_coefficients.json"

        # Step 1: Train coefficients (control vs 3D det)
        echo "Training bias correction coefficients ..."
        LD_PRELOAD= python3 "$BIAS_SCRIPT" train \
            --ctl-ncast "$CTL_NCAST" \
            --ctl-fcast "$CTL_FCAST" \
            --det-ncast "$DET_NCAST" \
            --det-fcast "$DET_FCAST" \
            --station-in "$STA_IN" \
            --nc-base "${PDY}${NC_HOUR}" \
            --fc-base "${PDY}${cyc}" \
            -o "$COEFF_FILE" >> $pgmout 2>&1
        train_rc=$?

        if [ $train_rc -ne 0 ] || [ ! -f "$COEFF_FILE" ]; then
            echo "WARNING: Bias correction training failed (rc=$train_rc), skipping"
        else
            echo "Coefficients saved: $COEFF_FILE"

            # Step 2: Apply correction to each perturbed member
            for member_dir in ${ENS_DIR}/member_*; do
                [ ! -d "$member_dir" ] && continue
                MEMBER_ID=$(basename "$member_dir" | sed 's/member_//')

                # Skip control member (anomaly = 0, result = 3D det)
                [ "$MEMBER_ID" = "000" ] && continue

                MEM_NCAST="$member_dir/${RUN}.${cycle}.restart_outputs/staout_1"
                MEM_FCAST="$member_dir/${RUN}.${cycle}.forecast_outputs/staout_1"

                # Also check flat layout
                [ ! -f "$MEM_NCAST" ] && MEM_NCAST="$member_dir/staout_1_nowcast"
                [ ! -f "$MEM_FCAST" ] && MEM_FCAST="$member_dir/staout_1_forecast"

                if [ ! -f "$MEM_NCAST" ] || [ ! -f "$MEM_FCAST" ]; then
                    echo "  Member $MEMBER_ID: staout files not found, skipping"
                    continue
                fi

                CORR_OUT="$member_dir/corrected_wl.csv"
                echo "  Correcting member $MEMBER_ID ..."
                LD_PRELOAD= python3 "$BIAS_SCRIPT" apply \
                    --coefficients "$COEFF_FILE" \
                    --det-ncast "$DET_NCAST" \
                    --det-fcast "$DET_FCAST" \
                    --ctl-ncast "$CTL_NCAST" \
                    --ctl-fcast "$CTL_FCAST" \
                    --member-ncast "$MEM_NCAST" \
                    --member-fcast "$MEM_FCAST" \
                    --station-in "$STA_IN" \
                    --nc-base "${PDY}${NC_HOUR}" \
                    --fc-base "${PDY}${cyc}" \
                    -o "$CORR_OUT" >> $pgmout 2>&1

                if [ $? -eq 0 ] && [ -f "$CORR_OUT" ]; then
                    echo "  Member $MEMBER_ID: corrected → $(basename $CORR_OUT)"
                else
                    echo "  Member $MEMBER_ID: correction failed"
                fi
            done
        fi
    else
        echo ""
        echo "Skipping ensemble bias correction (missing inputs):"
        [ ! -f "$BIAS_SCRIPT" ] && echo "  - bias correction script not found"
        [ ! -f "$DET_NCAST" ] && echo "  - 3D det nowcast not found: $DET_NCAST"
        [ ! -f "$DET_FCAST" ] && echo "  - 3D det forecast not found: $DET_FCAST"
        [ ! -f "$CTL_NCAST" ] && echo "  - 2D control nowcast not found: $CTL_NCAST"
        [ ! -f "$CTL_FCAST" ] && echo "  - 2D control forecast not found: $CTL_FCAST"
    fi
fi

echo ""
echo "============================================="
echo "COMF SCHISM post-processing completed"
echo "============================================="

exit $err
