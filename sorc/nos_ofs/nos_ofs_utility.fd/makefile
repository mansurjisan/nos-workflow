#! /bin/bash
#############################################################
#Makefile for nosofs utility library nosutil.a
# Use:
# # make - build the executable
# # make DEBUG=full - build the executalbe with debug options
# # make install - move the built executable into the $LIBnos dir
# # make clean - start with a clean slate
# ###############################################################
# # Tunable parameters:
# # FC Name of the FORTRAN compiling system to use
# # LDFLAGS Options of the loader
# # FFLAGS Options of the compiler
# # DEBUG Options of the compiler included for debugging
# # LIBS List of libraries
# # CMD Name of the executable
#

INCLUDES = -I.
AR = ar rv
RANLIB = ranlib
# add path to c compiler 
CC = $(COMP_CC) 
FC = $(COMP_F)
# add c compiler optimization flags
COPTIONS = -D_UNDERSCORE
FFLAGS = -O2
CFLAGS = $(COPTIONS) $(INCLUDES)

ifeq ($(DEBUG),full)
	FFLAGS = -DDEBUG -g -O0 -traceback -check all $(INCS)
endif

#CFLAGS = $(COPTIONS) $(FFLAGS) $(INCLUDES)
LD = $(CC) -L. 
LIB = libnosutil.a
OBJS =  stack.o stackpair.o volume.o interp_nneighbor.o interp_remesh.o interp_regrid.o utility.o nos_ofs_tideprediction.o equarg.o sal78.o


.c.o:
	$(CC) $(CFLAGS) -c stack.c stackpair.c volume.c
.F.o:

	$FC -c $(FFLAGS) -o interp_nneighbor.o interp_nneighbor.f
	$FC -c $(FFLAGS) -o interp_remesh.o interp_remesh.f
	$FC -c $(FFLAGS) -o interp_regrid.o interp_regrid.f
	$FC -c $(FFLAGS) -o utility.o utility.f
	$FC -c $(FFLAGS) -o nos_ofs_tideprediction.o nos_ofs_tideprediction.f
	$FC -c $(FFLAGS) -o equarg.o equarg.f
	$FC -c $(FFLAGS) -o sal78.o sal78.f
      
$(LIB): $(OBJS)
	$(AR) $@ $(OBJS)
	$(RANLIB) $@
#	mv $(LIB) ../../lib
#	rm -f $(OBJS)

clean:
	rm -f $(OBJS)

install:
	cp -p $(LIB) $(LIBnos)
realclean:
	rm -f *.o ; rm -f *.a
