# envir-p1.h - development stand-in for the NCO environment header. The job name carries the _<envir> suffix of the PBS cards,
# which pbs/clean_work.sh matches on. MJ (10/20/26)
export job=${job:-${PBS_JOBNAME}_${envir}}
export jobid=${jobid:-$job.$PBS_JOBID}

export PDY=%PDY%
