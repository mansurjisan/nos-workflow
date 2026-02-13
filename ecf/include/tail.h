########################################
# tail.h - Standard ecFlow tail for NOS-OFS unified workflow
#
# Notify ecFlow server that job completed successfully,
# clear the error trap, and exit cleanly.
########################################
ecflow_client --complete
trap 0
exit 0
