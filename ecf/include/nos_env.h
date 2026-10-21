# nos_env.h - system identity, from the suite variables. Before the module block. MJ (10/20/26)
export OFS=%OFS%
export NET=nos RUN=${OFS} PREFIXNOS=${OFS}
if [ -n "%NOS_ARCHIVE_MANIFEST:%" ]; then export NOS_ARCHIVE_MANIFEST=%NOS_ARCHIVE_MANIFEST:%; fi
if [ -n "%ADCIRC_MODE:%" ]; then export ADCIRC_MODE=%ADCIRC_MODE:%; fi
