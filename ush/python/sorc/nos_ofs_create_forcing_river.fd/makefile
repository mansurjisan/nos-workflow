#! /bin/bash 
#############################################################
#Makefile for  nos_ofs_create_forcing_river
# Use:
# make - build the executable
# make DEBUG=full - build the executalbe with debug options
# make install - move the built executable into the $LIBnos dir
# make clean - start with a clean slate
############################################################
# Tunable parameters:
# FC Name of the FORTRAN compiling system to use
# LDFLAGS Options of the loader
# FFLAGS Options of the compiler
# DEBUG Options of the compiler included for debugging
# LIBS List of libraries
# CMD Name of the executable
#
SRCS=nos_ofs_create_forcing_river.f nos_ofs_nwm_river.f 

OBJS=nos_ofs_create_forcing_river.o nos_ofs_nwm_river.o

FC =           $(COMP_F) 
#use for extensive compilation error reporting
#LDFLAGS = -p -bnoquiet -bloadmap:mug
LDFLAGS =	
#INC = -I/nwprod/lib/incmod/g2_4
INC = -I${G2_INC4}
NETCDF_INC = -I$(NETCDF)/include
NETCDF_LIB = -L$(NETCDF)/lib -lnetcdff

## NOS COMF unitility library
NOS_UTILITY_LIB = -L$(LIBnos) -lnosutil
INCS  = $(INC) $(NETCDF_INC)

LIB  =   ${G2_LIB4} ${W3NCO_LIB4} ${W3EMC_LIB4} ${BUFR_LIB4}\
   $(NOS_UTILITY_LIB) ${JASPER_LIB} ${PNG_LIB}  ${Z_LIB} ${BACIO_LIB4}

LIBS  = $(NETCDF_LIB) $(LIB)

CMD =            nos_ofs_create_forcing_river 
PROFLIB =       -lprof

# To perform the default compilation, use the first line
# To compile with flowtracing turned on, use the second line
# To compile giving profile additonal information, use the third line
# WARNING:  SIMULTANEOUSLY PROFILING AND FLOWTRACING IS NOT RECOMMENDED
FFLAGS =        -O3 -extend-source $(INCS)
ifeq ($(DEBUG),full)
        FFLAGS = -DDEBUG -g -O0 -traceback -check all -extend-source $(INCS)
endif

# Lines from here on down should not need to be changed.  They are the
# actual rules which make uses to build a.out.

all:		$(CMD)

$(CMD):		$(OBJS)
	$(FC) $(LDFLAGS)  -o $(@) $(OBJS) $(LIBS)
	rm -f $(OBJS)
#	cp -p  $(CMD) ../../exec/

# Make the profiled version of the command and call it a.out.prof

#$(FC) $(LDFLAGS)  -o $(@) $(OBJS) $(PROFLIB) $(LIBS)
install:
	cp -p $(CMD) $(EXECnos)/.
clean:
	rm -f $(OBJS)

clobber:	clean
	rm -f $(CMD) $(CMD).prof

void:	clobber
	rm -f $(SRCS) makefile
