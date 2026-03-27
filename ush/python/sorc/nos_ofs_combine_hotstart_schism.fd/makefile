SHELL=/bin/sh
#############################################################
# Makefile for nos_ofs_combine_hotstart_schism
# Use:
# make - build the executable
# make DEBUG=full - build the executable with debug options
# make install - move the built executable into the $EXECnos dir
# make clean - start with a clean slate
#
# NOTE: This executable uses "use netcdf" F90 module syntax which
# requires gfortran (not Intel) to work with system netcdf-fortran
############################################################

SRCS=argparse.f90 combine_hotstart7.f90

OBJS=$(SRCS:.f90=.o)

# Use gfortran for this executable (requires gfortran-compiled netcdf.mod)
FC = gfortran

LDFLAGS =

NETCDF_INC = -I$(NETCDF)/include -I/usr/lib64/gfortran/modules
NETCDF_LIB = -L$(NETCDF)/lib -lnetcdff -lnetcdf

INCS = $(NETCDF_INC)
LIBS = $(NETCDF_LIB)

CMD = nos_ofs_combine_hotstart_schism

FFLAGS = -O3 -cpp $(INCS)
ifeq ($(DEBUG),full)
	FFLAGS = -DDEBUG -g -O0 -fcheck=all -fbacktrace $(INCS)
endif

.SUFFIXES: .f90 .o

.f90.o:
	$(FC) $(FFLAGS) -c $<

all: $(CMD)

# Build argparse module first (combine_hotstart7 depends on it)
argparse.o: argparse.f90
	$(FC) $(FFLAGS) -c $<

combine_hotstart7.o: combine_hotstart7.f90 argparse.o
	$(FC) $(FFLAGS) -c $<

$(CMD): $(OBJS)
	$(FC) $(LDFLAGS) -o $(@) $(OBJS) $(LIBS)
	rm -f $(OBJS) *.mod

install:
	cp -p $(CMD) $(EXECnos)/

clean:
	rm -f $(OBJS)

clobber: clean
	rm -f $(CMD)

void: clobber
	rm -f $(SRCS) makefile
