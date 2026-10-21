# nos_env_adcirc.h - input paths of the STOFS-2D-Global cards, all four jobs. MJ (10/20/26)
export COMINgfs=${COMINgfs:-/lfs/h1/ops/prod/com/gfs/${gfs_ver:-v16.3}}
export EXECnos=${EXECnos:-${HOMEnos}/exec}
if [ -n "%ADCIRC_EXEC_DIR:%" ]; then export ADCIRC_EXEC_DIR=%ADCIRC_EXEC_DIR:%; fi
