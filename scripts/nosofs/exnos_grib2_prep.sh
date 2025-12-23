#!/bin/sh
# #########################################################################
#  Script Name: exnos_ofs_prep.sh
#  Purpose:                                                                #
#  This is the main script is launch sripts to generating forcing files    #
# Location:   ~/jobs
# Technical Contact:    Aijun Zhang         Org:  NOS/CO-OPS
#                       Phone: 301-7132890 ext. 127
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

export pgm="$USHnos/nos_grib2_launch.sh $OFS prep"
echo "run the launch script to set the NOS configuration"
. $USHnos/nos_grib2_launch.sh
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



#exit
