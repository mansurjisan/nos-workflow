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
SRCS=nos_ofs_adjust_tides.f
OBJS=nos_ofs_adjust_tides.o

FC = $(COMP_F) 

#use for extensive compilation error reporting
NETCDF_INC = -I$(NETCDF)/include
NETCDF_LIB = -L$(NETCDF)/lib -lnetcdff

## NOS COMF unitility library
NOS_UTILITY_LIB = -L$(LIBnos) -lnosutil
INCS = $(NETCDF_INC)
LIBS = $(NETCDF_LIB) $(NOS_UTILITY_LIB)

CMD =     nos_ofs_adjust_tides 

# To perform the default compilation, use the first line
# To compile with flowtracing turned on, use the second line
# To compile giving profile additonal information, use the third line
# WARNING:  SIMULTANEOUSLY PROFILING AND FLOWTRACING IS NOT RECOMMENDED
FFLAGS =  $(INCS) # -check all
ifeq ($(DEBUG),full)
	FFLAGS = -DDEBUG -g -O0 -traceback -check all $(INCS)
endif
all:	$(CMD)
$(CMD):	$(OBJS)
	$(FC) $(FFLAGS) -o $(@) $(OBJS) $(LIBS)
	rm -f $(OBJS)
install:
	cp -p $(CMD) $(EXECnos)/$(CMD)
clean:
	rm -f $(OBJS)
clobber: clean
	rm -f $(CMD) $(CMD).prof
void:	clobber
	rm -f $(SRCS) makefile

