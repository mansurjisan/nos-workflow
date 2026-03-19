#!/bin/sh
# #########################################################################
#  Script Name: exnos_ofs_prep.sh
#  Purpose:                                                                #
#  This is the main script is launch sripts to generating forcing files    #
# Location:   ~/jobs
# Technical Contact:    Aijun Zhang         Org:  NOS/CO-OPS
#                       Phone: 240-533-0591 
#                       E-Mail: aijun.zhang@noaa.gov
#
#  Usage: 
#
# Input Parameters:
#   OFS 
#
# Modification History:
#     Degui Cao     02/18/2010   
# #########################################################################

set -x
#PS4=" \${SECONDS} \${0##*/} L\${LINENO} + "

echo "Start ${RUN} Preparation " > $cormslogfile

# ============================================================================
# YAML Configuration Loading (Phase 1 Integration)
# ============================================================================
# Try loading YAML config first, fall back to legacy .ctl file
# Priority: OFS_CONFIG env var -> FIXofs YAML -> FIXofs .ctl

CONFIG_SOURCE="none"

# Option 1: Load from OFS_CONFIG environment variable (YAML)
if [ -n "$OFS_CONFIG" ] && [ -f "$OFS_CONFIG" ]; then
    echo "Loading configuration from YAML: $OFS_CONFIG"
    if [ -f "${USHnos}/nos_ofs_config.sh" ]; then
        . ${USHnos}/nos_ofs_config.sh
        if [ "${OFS_CONFIG_LOADED:-0}" -eq 1 ]; then
            CONFIG_SOURCE="yaml"
            echo "Successfully loaded YAML config from $OFS_CONFIG" >> $cormslogfile
        fi
    fi
fi

# Option 2: Check for YAML config in FIXofs
if [ "$CONFIG_SOURCE" = "none" ] && [ -f "${FIXofs}/${PREFIXNOS}.yaml" ]; then
    echo "Loading configuration from YAML: ${FIXofs}/${PREFIXNOS}.yaml"
    export OFS_CONFIG="${FIXofs}/${PREFIXNOS}.yaml"
    if [ -f "${USHnos}/nos_ofs_config.sh" ]; then
        . ${USHnos}/nos_ofs_config.sh
        if [ "${OFS_CONFIG_LOADED:-0}" -eq 1 ]; then
            CONFIG_SOURCE="yaml"
            echo "Successfully loaded YAML config from ${FIXofs}/${PREFIXNOS}.yaml" >> $cormslogfile
        fi
    fi
fi

# Option 3: Fall back to legacy .ctl file
if [ "$CONFIG_SOURCE" = "none" ]; then
    if [ -s ${FIXofs}/${PREFIXNOS}.ctl ]; then
        . ${FIXofs}/${PREFIXNOS}.ctl
        CONFIG_SOURCE="ctl"
        echo "Loaded legacy .ctl config from ${FIXofs}/${PREFIXNOS}.ctl" >> $cormslogfile
    else
        echo "${RUN} control file is not found"
        echo "please provide ${RUN} control file: ${PREFIXNOS}.yaml or ${PREFIXNOS}.ctl in ${FIXofs}"
        msg="${RUN} control file is not found"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
        echo "${RUN} control file is not found" >> $cormslogfile
        err_chk
    fi
fi

echo "Configuration loaded from: $CONFIG_SOURCE"
# ============================================================================

export pgm="$USHnos/nos_ofs_launch.sh $OFS prep"
echo "run the launch script to set the NOS configuration"
. $USHnos/nos_ofs_launch.sh $OFS prep
export err=$?
if [ $err -ne 0 ]
then
   echo "Execution of $pgm did not complete normally, FATAL ERROR!"
   echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile 
   msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
   err_chk
else
   echo "Execution of $pgm completed normally" >> $cormslogfile
   echo "Execution of $pgm completed normally"
   msg=" Execution of $pgm completed normally"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
fi

# =============================================================================
# Meteorological Forcing (sflux) Generation — Nowcast
# Skip for UFS-Coastal (USE_DATM): atmospheric forcing is handled by DATM
# via the DATM forcing generation step below.
# =============================================================================
if [ "${USE_DATM:-false}" != "true" ] && [ "${USE_DATM:-0}" != "1" ]; then

export metnum=1


echo "The script nos_ofs_create_forcing_met.sh nowcast  starts at time: " `date `
. prep_step
echo "Generating the meteorological forcing for nowcast"
export pgm=nos_ofs_create_forcing_met.sh
DBASE=$DBASE_MET_NOW
TIME_START_TMP=${time_hotstart}
TIME_END_TMP=$time_nowcastend
export pgm=nos_ofs_create_forcing_met.sh
$USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
#$USHnos/nos_ofs_create_forcing_met.sh nowcast
export err=$?
if [ $err -ne 0 ]
then
  echo "Execution of $pgm did not complete normally, FATAL ERROR!"
  echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
  msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
  postmsg "$jlogfile" "$msg"
  postmsg "$nosjlogfile" "$msg"
  err_chk
else
  echo "Execution of $pgm completed normally" >> $cormslogfile
  echo "Execution of $pgm completed normally"
  msg=" Execution of $pgm completed normally"
  postmsg "$jlogfile" "$msg"
  postmsg "$nosjlogfile" "$msg"
fi
if [ -s MET_DBASE.NOWCAST ]; then
  read DBASE < MET_DBASE.NOWCAST
  echo 'DBASE=' $DBASE 'DBASE_MET_NOW='  $DBASE_MET_NOW
  if [ $DBASE != $DBASE_MET_NOW ]; then
    DBASE_MET_NOW=$DBASE
    export DBASE_MET_NOW
  fi
fi

if [ $MET_NUM -eq 2 ]
then
export metnum=2

export pgm=nos_ofs_create_forcing_met.sh
DBASE=$DBASE_MET_NOW2
TIME_START_TMP=${time_hotstart}
TIME_END_TMP=$time_nowcastend
#TIME_START_TMP=` $NDATE -3 ${time_hotstart} `
#TIME_END_TMP=` $NDATE +6 ${time_nowcastend} `
export pgm=nos_ofs_create_forcing_met.sh
$USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
#$USHnos/nos_ofs_create_forcing_met.sh nowcast
export err=$?
if [ $err -ne 0 ]
then
  echo "Execution of $pgm did not complete normally, FATAL ERROR!"
  echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
  msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
  postmsg "$jlogfile" "$msg"
  postmsg "$nosjlogfile" "$msg"
  err_chk
else
  echo "Execution of $pgm completed normally" >> $cormslogfile
  echo "Execution of $pgm completed normally"
  msg=" Execution of $pgm completed normally"
  postmsg "$jlogfile" "$msg"
  postmsg "$nosjlogfile" "$msg"
fi
if [ -s MET_DBASE.NOWCAST ]; then
  read DBASE < MET_DBASE.NOWCAST
  echo 'DBASE=' $DBASE 'DBASE_MET_NOW='  $DBASE_MET_NOW
  if [ $DBASE != $DBASE_MET_NOW ]; then
    DBASE_MET_NOW=$DBASE
    export DBASE_MET_NOW
  fi
fi

fi

else
  echo "Skipping sflux nowcast generation (USE_DATM=true, atmospheric forcing via DATM)"
  echo "Skipping sflux nowcast generation (USE_DATM=true)" >> $cormslogfile
fi

# =============================================================================
# UFS-Coastal DATM Forcing Generation (run early, before OBC/river)
# When USE_DATM is enabled, generate DATM blended HRRR+GFS forcing,
# ESMF meshes, and UFS config files (model_configure, datm_in,
# datm.streams, ufs.configure).
# No dependency on river, OBC, or model config steps.
# =============================================================================
if [ "${USE_DATM:-false}" == "true" ] || [ "${USE_DATM:-0}" == "1" ]; then
    echo "============================================"
    echo "Generating UFS-Coastal DATM forcing..."
    echo "============================================"

    # Export variables needed by DATM scripts
    export DATM_BLEND_HRRR_GFS=${DATM_BLEND_HRRR_GFS:-true}
    export DATM_DOMAIN=${DATM_DOMAIN:-SECOFS}
    export BLEND_RESOLUTION=${BLEND_RESOLUTION:-0.025}
    export BLEND_BUFFER_DEG=${BLEND_BUFFER_DEG:-0.5}
    export NHOURS_FCST=${LEN_FORECAST:-48}
    export DT_ATMOS=${DT_ATMOS:-720}
    export NHOUR=${NHOUR:-nhour}
    # DATM input directory and file naming
    export DATM_INPUT_DIR=${DATM_INPUT_DIR:-INPUT}
    export DATM_MESH_FILE=${DATM_MESH_FILE:-datm_esmf_mesh.nc}
    export DATM_FORCING_FILE=${DATM_FORCING_FILE:-datm_forcing.nc}

    # -----------------------------------------------------------------------
    # Two paths for DATM forcing:
    #   grib2 (default): Extract from raw GRIB2 via wgrib2+Python blend
    #   sflux (backup):  Run COMF sflux generation, convert to DATM format
    #                    (strict validation — identical to standalone SCHISM)
    # -----------------------------------------------------------------------
    export DATM_FORCING_SOURCE=${DATM_FORCING_SOURCE:-grib2}

    if [ "${DATM_FORCING_SOURCE}" == "sflux" ]; then
        echo "DATM_FORCING_SOURCE=sflux: generating sflux first, then converting to DATM"

        # --- Step 1: Run sflux NOWCAST generation (same as non-DATM path) ---
        export metnum=1
        echo "Running sflux nowcast for DATM conversion..."
        DBASE=$DBASE_MET_NOW
        TIME_START_TMP=${time_hotstart}
        TIME_END_TMP=$time_nowcastend
        $USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
        export err=$?
        if [ $err -ne 0 ]; then
            echo "sflux nowcast generation failed, FATAL ERROR!" >> $cormslogfile
            msg="sflux nowcast generation for DATM failed"
            postmsg "$jlogfile" "$msg"
            err_chk
        fi
        echo "sflux nowcast completed" >> $cormslogfile

        # Second met source (HRRR) for nowcast
        if [ ${MET_NUM:-1} -eq 2 ]; then
            export metnum=2
            DBASE=$DBASE_MET_NOW2
            $USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
            export err=$?
            if [ $err -ne 0 ]; then
                msg="sflux nowcast (met2) for DATM failed"
                postmsg "$jlogfile" "$msg"
                err_chk
            fi
        fi

        # --- Step 2: Run sflux FORECAST generation ---
        export metnum=1
        if [ ${LEN_FORECAST:-0} -gt 0 ]; then
            echo "Running sflux forecast for DATM conversion..."
            DBASE=${DBASE_MET_FOR%:*}
            TIME_START_TMP=${time_nowcastend}
            TIME_END_TMP=$time_forecastend
            $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
            export err=$?
            if [ $err -ne 0 ]; then
                msg="sflux forecast generation for DATM failed"
                postmsg "$jlogfile" "$msg"
                err_chk
            fi
            echo "sflux forecast completed" >> $cormslogfile

            if [ ${MET_NUM:-1} -eq 2 ]; then
                export metnum=2
                DBASE=$DBASE_MET_FOR2
                $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
                export err=$?
                if [ $err -ne 0 ]; then
                    msg="sflux forecast (met2) for DATM failed"
                    postmsg "$jlogfile" "$msg"
                    err_chk
                fi
            fi
        fi

        # --- Step 3: Convert sflux to DATM format ---
        echo "Converting sflux to DATM forcing format..."
        SFLUX_DIR="${DATA}"
        DATM_OUTPUT="${DATA}/${DATM_INPUT_DIR}/${DATM_FORCING_FILE}"
        mkdir -p ${DATA}/${DATM_INPUT_DIR}

        # Unset LD_PRELOAD to avoid conflicts with Python/scipy
        _saved_LD_PRELOAD="${LD_PRELOAD:-}"
        unset LD_PRELOAD

        python3 ${USHnos}/python/nos_ofs/datm/sflux_to_datm.py \
            --sflux-dir "${SFLUX_DIR}" \
            --output "${DATM_OUTPUT}" \
            --pdy "${PDY}" --cyc "${cyc}" \
            --lat-min ${MINLAT} --lat-max ${MAXLAT} \
            --lon-min ${MINLON} --lon-max ${MAXLON} \
            --dx ${BLEND_RESOLUTION} \
            --scrip "${DATA}/${DATM_INPUT_DIR}/datm_scrip.nc"
        export err=$?

        # Restore LD_PRELOAD
        if [ -n "$_saved_LD_PRELOAD" ]; then
            export LD_PRELOAD="$_saved_LD_PRELOAD"
        fi

        if [ $err -ne 0 ]; then
            echo "sflux-to-DATM conversion failed, FATAL ERROR!" >> $cormslogfile
            msg="sflux-to-DATM conversion failed"
            postmsg "$jlogfile" "$msg"
            err_chk
        fi
        echo "sflux-to-DATM conversion completed" >> $cormslogfile

        # --- Step 4: Generate ESMF mesh from SCRIP ---
        if command -v ESMF_Scrip2Unstruct &> /dev/null; then
            echo "Generating ESMF mesh from SCRIP..."
            ESMF_Scrip2Unstruct \
                ${DATA}/${DATM_INPUT_DIR}/datm_scrip.nc \
                ${DATA}/${DATM_INPUT_DIR}/${DATM_MESH_FILE} 0
        else
            echo "WARNING: ESMF_Scrip2Unstruct not available, skipping mesh generation"
        fi

        # --- Step 5: Generate UFS config files ---
        ${USHnos}/nosofs/nos_ofs_gen_ufs_config.sh
        export err=$?
        if [ $err -ne 0 ]; then
            msg="UFS config generation failed"
            postmsg "$jlogfile" "$msg"
            err_chk
        fi

    else
        # Default path: GRIB2 pipeline
        echo "DATM_FORCING_SOURCE=grib2: extracting from raw GRIB2 files"

        # Run blended forcing orchestrator
        ${USHnos}/nosofs/nos_ofs_create_datm_forcing_blended.sh ${DATM_DOMAIN}
        export err=$?
        if [ $err -ne 0 ]; then
            echo "DATM forcing generation failed, FATAL ERROR!"
            echo "DATM forcing generation failed, FATAL ERROR!" >> $cormslogfile
            msg="DATM forcing generation failed, FATAL ERROR!"
            postmsg "$jlogfile" "$msg"
            err_chk
        else
            echo "DATM forcing generation completed normally"
            echo "DATM forcing generation completed normally" >> $cormslogfile
            msg="DATM forcing generation completed normally"
            postmsg "$jlogfile" "$msg"
        fi
    fi

    # Archive DATM artifacts to COMOUT (both paths)
    DATM_DIR=${DATM_INPUT_DIR:-INPUT}
    mkdir -p $COMOUT/${RUN}.${cycle}.datm_input
    if [ -d ${DATA}/${DATM_DIR} ]; then
        cp -p ${DATA}/${DATM_DIR}/*.nc $COMOUT/${RUN}.${cycle}.datm_input/ 2>/dev/null || true
    fi
    for f in model_configure datm_in datm.streams ufs.configure fd_ufs.yaml noahmptable.tbl; do
        [ -s "${DATA}/${f}" ] && cp -p "${DATA}/${f}" "$COMOUT/${RUN}.${cycle}.${f}"
    done
    echo "DATM artifacts archived to $COMOUT"
fi

echo "The script nos_ofs_create_forcing_river.sh starts at time: " `date `
echo "Generating the river forcing"
export pgm=nos_ofs_create_forcing_river.sh
. prep_step
$USHnos/nos_ofs_create_forcing_river.sh
export err=$?
if [ $err -ne 0 ]
then
  echo "Execution of $pgm did not complete normally, FATAL ERROR!"
  echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile 
  msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
  postmsg "$jlogfile" "$msg"
  postmsg "$nosjlogfile" "$msg"
  err_chk
else
  echo "Execution of $pgm completed normally"
  echo "Execution of $pgm completed normally" >> $cormslogfile
  msg=" Execution of $pgm completed normally"
  postmsg "$jlogfile" "$msg"
  postmsg "$nosjlogfile" "$msg"
fi



if [ "${OFS,,}" != "lsofs" -a "${OFS,,}" != "loofs" ]; then
  echo "The script nos_ofs_create_forcing_obc.sh starts at time: " `date `
  echo "Generating the open boundary forcing"
  if [ "${BAROTROPIC:-false}" == "true" ] || [ "${BAROTROPIC:-0}" == "1" ]; then
      # Barotropic: skip Fortran OBC for T/S/velocity but optionally
      # generate elev2D.th.nc from RTOFS SSH for subtidal elevation BC
      echo "  Barotropic mode: skipping 3D OBC (T/S/velocity)"

      # Try to generate elev2D.th.nc from RTOFS SSH data
      _gen_elev="${FIXofs}/gen_elev2d_th.py"
      [ ! -f "$_gen_elev" ] && _gen_elev="${HOMEnos:-}/fix/${OFS}/gen_elev2d_th.py"
      _hgrid_ll="${FIXofs}/${GRIDFILE_LL:-${PREFIXNOS}.hgrid.ll}"
      _ndays=$(echo "scale=2; (${LEN_NOWCAST:-6} + ${LEN_FORECAST:-48}) / 24 + 0.5" | bc)
      _elev2d_ok=false

      if [ -f "$_gen_elev" ] && [ -d "${COMINrtofs:-/dev/null}" ] && [ -f "$_hgrid_ll" ]; then
          echo "  Generating elev2D.th.nc from RTOFS SSH (ndays=${_ndays})"
          _elev_log=${DATA}/gen_elev2d_th.log
          # Strip MKL/MPI paths from LD_LIBRARY_PATH to avoid numpy segfault,
          # but keep Intel base libs (libifport.so.5 needed by python3 itself)
          _saved_ldlp="${LD_LIBRARY_PATH:-}"
          export LD_LIBRARY_PATH=$(echo "$_saved_ldlp" | tr ':' '\n' | \
              grep -v -E 'mkl|mpi|mpich|cray-mpich' | tr '\n' ':' | sed 's/:$//')
          python3 $_gen_elev "$_hgrid_ll" "${COMINrtofs}" \
              "${PDY}" "${cyc}" "${_ndays}" \
              --dt 21600 --ssh-offset ${SSH_OFFSET:-0.04} \
              -o ${DATA}/elev2D.th.nc > ${_elev_log} 2>&1
          _elev_rc=$?
          export LD_LIBRARY_PATH="$_saved_ldlp"
          cat ${_elev_log}
          cat ${_elev_log} >> $pgmout
          if [ $_elev_rc -eq 0 ] && [ -s "${DATA}/elev2D.th.nc" ]; then
              echo "  Successfully generated elev2D.th.nc"
              _elev2d_ok=true
              # Also archive to COMOUTrerun for staging by model job
              cp -p ${DATA}/elev2D.th.nc ${COMOUTrerun}/${RUN}.${cycle}.elev2dth.nc 2>/dev/null || true
          else
              echo "  WARNING: gen_elev2d_th.py failed (rc=${_elev_rc}), falling back to tidal-only"
              [ -f ${_elev_log} ] && echo "  --- gen_elev2d_th.py output ---" && cat ${_elev_log} && echo "  --- end ---"
          fi
      else
          echo "  RTOFS SSH generation skipped (missing gen_elev2d_th.py, COMINrtofs, or hgrid.ll)"
      fi

      # Convert bctides.in to strip T/S; use --with-elev2d if elev2D.th.nc was generated
      _convert_script="${FIXofs}/convert_bctides_2d.py"
      [ ! -f "$_convert_script" ] && _convert_script="${HOMEnos:-}/fix/${OFS}/convert_bctides_2d.py"
      _elev_flag=""
      $_elev2d_ok && _elev_flag="--with-elev2d"
      for _bct in ${DATA}/${PREFIXNOS}.bctides.in ${DATA}/bctides.in; do
          if [ -f "$_bct" ] && [ -f "$_convert_script" ]; then
              python3 $_convert_script $_elev_flag "$_bct" "${_bct}.2d"
              mv "${_bct}.2d" "$_bct"
              echo "  Converted: $(basename $_bct) ${_elev_flag:+(iettype=4: tidal+subtidal)}"
          fi
      done

      # Create OBC tar (elev2D.th.nc is real if generated, empty placeholders for T/S)
      touch ${DATA}/TEM_nu.nc ${DATA}/TEM_3D.th.nc ${DATA}/SAL_nu.nc \
            ${DATA}/SAL_3D.th.nc ${DATA}/uv3D.th.nc
      [ ! -f "${DATA}/elev2D.th.nc" ] && touch ${DATA}/elev2D.th.nc
      tar -C ${DATA} -cvf ${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.obc.tar \
          TEM_nu.nc TEM_3D.th.nc SAL_nu.nc SAL_3D.th.nc elev2D.th.nc uv3D.th.nc 2>/dev/null || true
      echo "  Created OBC tar (elev2D.th.nc: $($_elev2d_ok && echo 'from RTOFS' || echo 'placeholder'))"
      export err=0
  else
  export pgm=nos_ofs_create_forcing_obc.sh
  . prep_step
  $USHnos/nos_ofs_create_forcing_obc.sh
  export pgm=nos_ofs_create_forcing_obc.sh
  . prep_step
  $USHnos/nos_ofs_create_forcing_obc.sh
  export err=$?
  if [ $err -ne 0 ];  then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!"
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
  fi  # end else (non-barotropic OBC)
  # Convert bctides.in in BOTH DATA and COMOUT for barotropic
  # Must convert DATA copy too, because later steps may copy it back to COMOUT
  if [ "${BAROTROPIC:-false}" == "true" ] || [ "${BAROTROPIC:-0}" == "1" ]; then
      local _convert_script="${FIXofs}/convert_bctides_2d.py"
      [ ! -f "$_convert_script" ] && _convert_script="${HOMEnos}/fix/${OFS}/convert_bctides_2d.py"
      if [ -f "$_convert_script" ]; then
          # Convert in DATA (source for any subsequent copies)
          for _bct in ${DATA}/${PREFIXNOS}.bctides.in ${DATA}/bctides.in; do
              if [ -f "$_bct" ]; then
                  python3 $_convert_script "$_bct" "${_bct}.2d"
                  mv "${_bct}.2d" "$_bct"
                  echo "  Converted DATA: $(basename $_bct)"
              fi
          done
          # Convert in COMOUT (already archived copies)
          for _bct in ${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.bctides.in.nowcast \
                      ${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.bctides.in.forecast; do
              if [ -f "$_bct" ]; then
                  python3 $_convert_script "$_bct" "${_bct}.2d"
                  mv "${_bct}.2d" "$_bct"
                  echo "  Converted COMOUT: $(basename $_bct)"
              fi
          done
      fi
  fi
fi
TS_NUDGING=${TS_NUDGING:-0}
if [ $TS_NUDGING -eq 1 ]; then
  echo "Generating the forcing for T/S nudging fields"
  export pgm=nos_ofs_create_forcing_nudg.sh
  . prep_step
  $USHnos/nos_ofs_create_forcing_nudg.sh
  export err=$?
  if [ $err -ne 0 ]
  then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!"
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
fi




# =============================================================================
# Meteorological Forcing (sflux) Generation — Forecast
# Skip for UFS-Coastal (USE_DATM): atmospheric forcing is handled by DATM.
# =============================================================================
if [ "${USE_DATM:-false}" != "true" ] && [ "${USE_DATM:-0}" != "1" ]; then

export metnum=1

if [ $LEN_FORECAST -gt 0 ]; then
  echo "The script nos_ofs_create_forcing_met.sh forecast starts at time: " `date `
  echo "Generating the meteorological forcing for forecst"
# added for blended met forcing source, e.g. HRRR:NDFD
  res="${DBASE_MET_FOR//[^:]}"
  nnn=${#res}
  export nfore=$((nnn + 1))

#export DBASE_MET_FOR1=${DBASE_MET_FOR%:*}
#export DBASE_MET_FOR2=${DBASE_MET_FOR#*:}

 if [ $nfore -eq 1 ]; then
  DBASE=${DBASE_MET_FOR%:*}
  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=$time_forecastend
  export pgm=nos_ofs_create_forcing_met.sh
  $USHnos/nos_ofs_create_forcing_met.sh forecast  $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!"
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"

  fi
 elif  [ $nfore -eq 2 ]; then
  DBASE=${DBASE_MET_FOR%:*}
  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=` $NDATE +48 $TIME_START_TMP `
  export pgm=nos_ofs_create_forcing_met.sh
  export met_fore_round=1
  $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" 
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
## read in DBASE used in actual  met forcing generating
    if [ -s MET_DBASE.FORECAST ]; then
       read DBASE < MET_DBASE.FORECAST
       echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
    fi
#    cp -p $MET_NETCDF_1_FORECAST ${MET_NETCDF_1_FORECAST}.$DBASE
#    cp -p $MET_NETCDF_2_FORECAST ${MET_NETCDF_2_FORECAST}.$DBASE 
     cp -p $MET_NETCDF_1_FORECAST"1" ${MET_NETCDF_1_FORECAST}.$DBASE
     cp -p $MET_NETCDF_2_FORECAST"1" ${MET_NETCDF_2_FORECAST}.$DBASE
  fi

  DBASE=${DBASE_MET_FOR#*:}
#  TIME_START_TMP=$TIME_END_TMP
  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=${time_forecastend}
  export pgm=nos_ofs_create_forcing_met.sh
  export met_fore_round=2
  $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
     echo "Execution of $pgm did not complete normally, FATAL ERROR!"
     echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
     msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
     postmsg "$jlogfile" "$msg"
     postmsg "$nosjlogfile" "$msg"
     err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
## read in DBASE used in actual  met forcing generating
    if [ -s MET_DBASE.FORECAST ]; then
      read DBASE < MET_DBASE.FORECAST
      echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
    fi
#    cp -p $MET_NETCDF_1_FORECAST ${MET_NETCDF_1_FORECAST}.$DBASE
#    cp -p $MET_NETCDF_2_FORECAST ${MET_NETCDF_2_FORECAST}.$DBASE   
     mv $MET_NETCDF_1_FORECAST"2" ${MET_NETCDF_1_FORECAST}.$DBASE
     mv $MET_NETCDF_2_FORECAST"2" ${MET_NETCDF_2_FORECAST}.$DBASE
     rm  $MET_NETCDF_1_FORECAST"1"
     rm  $MET_NETCDF_2_FORECAST"1"
  fi
 fi

#############################################################   machuan

if [ $MET_NUM -eq 2 ]
then
export metnum=2
DBASE=$DBASE_MET_FOR2

  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=${time_forecastend}
  export pgm=nos_ofs_create_forcing_met.sh
  $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
     echo "Execution of $pgm did not complete normally, FATAL ERROR!"
     echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
     msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
     postmsg "$jlogfile" "$msg"
     postmsg "$nosjlogfile" "$msg"
     err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
## read in DBASE used in actual  met forcing generating
    if [ -s MET_DBASE.FORECAST ]; then
      read DBASE < MET_DBASE.FORECAST
      echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
    fi
#    cp -p $MET_NETCDF_1_FORECAST ${MET_NETCDF_1_FORECAST}.$DBASE
#    cp -p $MET_NETCDF_2_FORECAST ${MET_NETCDF_2_FORECAST}.$DBASE
     mv $MET_NETCDF_1_FORECAST"2" ${MET_NETCDF_1_FORECAST}.$DBASE
     mv $MET_NETCDF_2_FORECAST"2" ${MET_NETCDF_2_FORECAST}.$DBASE
     rm  $MET_NETCDF_1_FORECAST"1"
     rm  $MET_NETCDF_2_FORECAST"1"
  fi
fi 

##################################


## read in DBASE used in actual  met forcing generating
 if [ -s MET_DBASE.FORECAST ]; then
  read DBASE < MET_DBASE.FORECAST
  echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
  if [ $DBASE != $DBASE_MET_FOR ]; then
    DBASE_MET_FOR=$DBASE
    export DBASE_MET_FOR
  fi
 fi
 echo "The script nos_ofs_create_forcing_met.sh forecast ended at time: " `date `
fi

else
  echo "Skipping sflux forecast generation (USE_DATM=true, atmospheric forcing via DATM)"
  echo "Skipping sflux forecast generation (USE_DATM=true)" >> $cormslogfile
fi

if [ ${OCEAN_MODEL} == "FVCOM" -o ${OCEAN_MODEL} == "fvcom" ]
then

 echo "Preparing FVCOM Control File for nowcast"
 export pgm="nos_ofs_prep_fvcom_ctl.sh  $OFS nowcast"
 $USHnos/nos_ofs_prep_fvcom_ctl.sh  $OFS nowcast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   err_chk
 else
   echo "Execution of nowcast ctl completed normally"
   echo "Execution of nowcast ctl completed normally" >> $cormslogfile
   msg=" Execution of nowcast ctl completed normally"
   postmsg "$jlogfile" "$msg"
 fi

 if [ $LEN_FORECAST -gt 0 ]; then
 echo "Preparing FVCOM Control File for forecast"
 $USHnos/nos_ofs_prep_fvcom_ctl.sh  $OFS forecast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! "
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! " >> $cormslogfile
   msg=" Execution of forecast ctl did not complete normally, FATAL ERROR! "
   postmsg "$jlogfile" "$msg"
   err_chk
 else
  echo "Execution of forecast ctl completed normally"
  echo "Execution of forecast ctl completed normally" >> $cormslogfile
  msg=" Execution of forecast ctl completed normally"
  postmsg "$jlogfile" "$msg"
 fi
 fi
elif [ ${OCEAN_MODEL} == "ROMS" -o ${OCEAN_MODEL} == "roms" ]
then
  echo "Preparing ROMS Control File for nowcast"
  export pgm=nos_ofs_prep_roms_ctl.sh
  . prep_step
  $USHnos/nos_ofs_prep_roms_ctl.sh  $OFS nowcast
  export err=$?
  if [ $err -ne 0 ]
  then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!"
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile 
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
  if [ $LEN_FORECAST -gt 0 ]; then
  echo "Preparing ROMS Control File for forecast"
  export pgm=nos_ofs_prep_roms_ctl.sh
  . prep_step
  $USHnos/nos_ofs_prep_roms_ctl.sh  $OFS forecast
  export err=$?
  if [ $err -ne 0 ]
  then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!"
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
  fi
elif [ ${OCEAN_MODEL} == "SELFE" -o ${OCEAN_MODEL} == "selfe" -o ${OCEAN_MODEL} == "SCHISM" -o ${OCEAN_MODEL} == "schism" ]
#elif [ ${OCEAN_MODEL} == "SCHISM" -o ${OCEAN_MODEL} == "schism" ]


then

# echo "Preparing SELFE Control File for nowcast"
 echo "Preparing SCHISM Control File for nowcast"

 export pgm="nos_ofs_prep_schism_ctl.sh  $OFS nowcast"
 $USHnos/nos_ofs_prep_schism_ctl.sh  $OFS nowcast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   err_chk
 else
   echo "Execution of nowcast ctl completed normally"
   echo "Execution of nowcast ctl completed normally" >> $cormslogfile
   msg=" Execution of nowcast ctl completed normally"
   postmsg "$jlogfile" "$msg"
 fi

#############

tar -cvf ${NWM_SOURCE_SINK_NOW} -C ./data/ .

cp ${NWM_SOURCE_SINK_NOW} ${COMOUT}/${NWM_SOURCE_SINK_NOW}

read rnday < "nowcast_running_day"
ns=$(echo "scale=0; $rnday * 3600 *24" | bc)
nsecond=$(printf "%.0f\n" "$ns")

cd ./data

for i in vsink.th vsource.th  msource.th;
do
        awk -v  awk_var=$nsecond '{ $1 = $1 - awk_var ; print }' $i  >  $i.new
        awk '$1 >= 0'  $i.new >  $i.new.new
        mv $i.new.new $i
done
rm *.new
cd ..

tar -cvf ${NWM_SOURCE_SINK_FORE} -C ./data/ .
cp ${NWM_SOURCE_SINK_FORE} ${COMOUT}/${NWM_SOURCE_SINK_FORE}


#############



 if [ $LEN_FORECAST -gt 0 ]; then
# echo "Preparing SELFE Control File for forecast"
 echo "Preparing SCHISM Control File for forecast"

 $USHnos/nos_ofs_prep_schism_ctl.sh  $OFS forecast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! "
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! " >> $cormslogfile
   msg=" Execution of forecast ctl did not complete normally, FATAL ERROR! "
   postmsg "$jlogfile" "$msg"
   err_chk
 else
  echo "Execution of forecast ctl completed normally"
  echo "Execution of forecast ctl completed normally" >> $cormslogfile
  msg=" Execution of forecast ctl completed normally"
  postmsg "$jlogfile" "$msg"
 fi
 fi
fi

cp -p $jlogfile $COMOUT

# Final barotropic bctides conversion — must be LAST to prevent overwrites
if [ "${BAROTROPIC:-false}" == "true" ] || [ "${BAROTROPIC:-0}" == "1" ]; then
    _convert_script="${FIXofs}/convert_bctides_2d.py"
    [ ! -f "$_convert_script" ] && _convert_script="${HOMEnos}/fix/${OFS}/convert_bctides_2d.py"
    if [ -f "$_convert_script" ]; then
        echo "  Final barotropic bctides conversion (iettype 5->3, strip T/S)..."
        for _bct in ${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.bctides.in.nowcast \
                    ${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.bctides.in.forecast; do
            if [ -f "$_bct" ]; then
                python3 $_convert_script "$_bct" "${_bct}.2d"
                mv "${_bct}.2d" "$_bct"
                echo "  Final converted: $(basename $_bct)"
            fi
        done
    fi
fi

	   echo "			  "
	   echo "END OF PREP SUCCESSFULLY "
	   echo "			  "

#exit
