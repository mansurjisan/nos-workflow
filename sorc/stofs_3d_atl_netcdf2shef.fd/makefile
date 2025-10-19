#############################################################
# Complete Makefile for stofs_3d_atl_netcdf2shef (matching original)
#############################################################

SRCS = stofs_3d_atl_netcdf2shef.f
OBJS = stofs_3d_atl_netcdf2shef.o

# Use ifort for Intel build (WCOSS2 compatible)
FC = ifort
LDFLAGS = -cpp -DHAVE_NETCDF4 -DNETCDF_CAN_DEFLATE

# Include paths (equivalent to original G2_INC4, NETCDF_INCLUDES, HDF5_INCLUDES, Z_INC)
INCS = -I/opt/ncep/include -I/usr/lib64/gfortran/modules -I/usr/include

# Complete library set matching original Intel makefile
# Original: G2_LIB4 W3NCO_LIB4 W3EMC_LIB4 BACIO_LIB4 BUFR_LIB4 JASPER_LIB PNG_LIB + netcdf/hdf5/zlib
LIBS = -L/opt/ncep/lib64 -L/opt/ncep/lib -L/usr/lib64 \
       -lg2_4 -lw3nco_4 -lw3emc_4 -lbacio -lbufr_4 \
       -ljasper -lpng -lnetcdf -lnetcdff -lhdf5 -lz

CMD = stofs_3d_atl_netcdf2shef

# Intel Fortran compiler flags (using fp-model strict for WCOSS2 compatibility)
FFLAGS = -O2 -fp-model strict $(INCS)

ifeq ($(DEBUG),full)
# Intel debug flags
FFLAGS = -DDEBUG -g -O0 -traceback -check all $(INCS)
endif

# Build rules
all: $(CMD)

$(CMD): $(OBJS)
	@echo "Linking $(CMD)..."
	$(FC) $(LDFLAGS) -o $@ $(OBJS) $(LIBS)
	rm -f $(OBJS)
	@echo "Build successful!"

install: all
	mkdir -p build
	cp $(CMD) build/
	@echo "Executable installed in build/ directory"

clean:
	rm -f $(OBJS) $(CMD) build/$(CMD)

# Compilation rule
$(OBJS): $(SRCS)
	@echo "Compiling $(SRCS)..."
	$(FC) $(FFLAGS) -c $(SRCS)

.PHONY: all install clean
