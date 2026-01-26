#! /bin/bash
#############################################################
#Makefile for  nos_ofs_adjust_tides
# Use:
# make - build the executable
# make DEBUG=full - build the executalbe with debug options
# make install - move the built executable into the $LIBnos dir
# make clean - start with a clean slate
# ###########################################################
# Tunable parameters:
# FC Name of the FORTRAN compiling system to use
# LDFLAGS Options of the loader
# FFLAGS Options of the compiler
# DEBUG Options of the compiler included for debugging
# LIBS List of libraries
# CMD Name of the executable
#
SRCS=nos_ofs_create_forcing_met.f nos_ofs_met_write_netcdf_ROMS.f w3fc07.f
OBJS=nos_ofs_create_forcing_met.o nos_ofs_met_write_netcdf_ROMS.o w3fc07.o

FC = ${COMP_F} 
#use for extensive compilation error reporting
LDFLAGS =	
INC = -I${G2_INC4}
NETCDF_INC = -I$(NETCDF)/include
NETCDF_LIB = -L$(NETCDF)/lib -lnetcdff

# NOS COMF unitility library
NOS_UTILITY_LIB = -L$(LIBnos) -lnosutil
INCS = $(INC) $(NETCDF_INC)

LIB  = ${G2_LIB4} ${W3NCO_LIB4} ${W3EMC_LIB4} \
   $(NOS_UTILITY_LIB) ${JASPER_LIB} $(PNG_LIB) ${Z_LIB} ${BACIO_LIB4}
LIBS  = $(NETCDF_LIB) $(LIB) 

CMD =     nos_ofs_create_forcing_met 
PROFLIB = -lprof

# To perform the default compilation, use the first line
# To compile with flowtracing turned on, use the second line
# To compile giving profile additonal information, use the third line
# WARNING:  SIMULTANEOUSLY PROFILING AND FLOWTRACING IS NOT RECOMMENDED
FFLAGS =        -O3 $(INCS)  -extend-source # -check all
ifeq ($(DEBUG),full)
     FFLAGS = -DDEBUG -g -O0 -traceback -check all -extend-source $(INCS)
endif
# Lines from here on down should not need to be changed.  They are the
# actual rules which make uses to build a.out.

all:	$(CMD)

$(CMD):	$(OBJS)
	$(FC) $(LDFLAGS) -o $(@) $(OBJS) $(LIBS)
	rm -f $(OBJS)
install:
	cp -p $(CMD) $(EXECnos)/nos_ofs_create_forcing_met
clean:
	rm -f $(OBJS)

clobber:	clean
	rm -f $(CMD) $(CMD).prof

void:	clobber
	rm -f $(SRCS) makefile
	if [ -s $(CMD) ]
	then
	echo copy $CMD
	  cp -p  $(CMD) ../../exec/
	fi

