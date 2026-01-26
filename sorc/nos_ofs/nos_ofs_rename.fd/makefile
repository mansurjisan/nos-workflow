#! /bin/bash 
#############################################################
#Makefile for  nos_ofs_rename
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
SRCS=nos_ofs_rename.f

OBJS=nos_ofs_rename.o

FC =  $(COMP_F)
#use for extensive compilation error reporting
#LDFLAGS = -p -bnoquiet -bloadmap:mug
LDFLAGS =	
#INC = -I/nwprod/lib/incmod/g2_4
INC = -I${G2_INC4}
NETCDF_INC = -I$(NETCDF)/include
NETCDF_LIB = -L$(NETCDF)/lib -lnetcdff

## NOS COMF unitility library
NOS_UTILITY_LIB = -L$(LIBnos) -lnosutil
INCS  = $(NETCDF_INC)

LIB  =   $(NOS_UTILITY_LIB) 

LIBS  = $(NETCDF_LIB) $(LIB)

CMD =             nos_ofs_rename 
PROFLIB =       -lprof

# To perform the default compilation, use the first line
# To compile with flowtracing turned on, use the second line
# To compile giving profile additonal information, use the third line
# WARNING:  SIMULTANEOUSLY PROFILING AND FLOWTRACING IS NOT RECOMMENDED
FFLAGS =        -O3  $(INCS)   -extend-source
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
install:
	cp -p $(CMD) $(EXECnos)/.
# Make the profiled version of the command and call it a.out.prof

#$(FC) $(LDFLAGS)  -o $(@) $(OBJS) $(PROFLIB) $(LIBS)

clean:
	rm -f $(OBJS)

clobber:	clean
	rm -f $(CMD) $(CMD).prof

void:	clobber
	rm -f $(SRCS) makefile
