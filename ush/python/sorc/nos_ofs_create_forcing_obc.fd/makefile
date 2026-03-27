#! /bin/bash
#############################################################
#Makefile for  nos_ofs_create_forcing_obc
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
SRCS=nos_ofs_create_forcing_obc.f  nos_ofs_obc_write_netcdf_ROMS.f
OBJS=nos_ofs_create_forcing_obc.o  nos_ofs_obc_write_netcdf_ROMS.o

FC =  $(COMP_F)
#use for extensive compilation error reporting
LDFLAGS =	
INC = -I${G2_INC4}
NETCDF_INC = -I$(NETCDF)/include
NETCDF_LIB = -L$(NETCDF)/lib -lnetcdff

# NOS COMF unitility library
NOS_UTILITY_LIB = -L$(LIBnos) -lnosutil
INCS = $(INC) $(NETCDF_INC)
LIB  = ${G2_LIB4} ${W3NCO_LIB4} ${W3EMC_LIB4} ${BUFR_LIB4}\
   $(NOS_UTILITY_LIB) ${JASPER_LIB} ${PNG_LIB} ${Z_LIB4} ${BACIO_LIB4}
LIBS = $(NETCDF_LIB) $(LIB)
CMD =  nos_ofs_create_forcing_obc
PROFLIB = -lprof

FFLAGS = -O3 $(INCS) -extend-source 
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
	cp -p $(CMD) $(EXECnos)/nos_ofs_create_forcing_obc
clean:
	rm -f $(OBJS)
clobber: clean
	rm -f $(CMD) $(CMD).prof
void:	clobber
	rm -f $(SRCS) makefile

