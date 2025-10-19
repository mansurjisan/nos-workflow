# Intel Fortran Compiler Support for WCOSS2

This directory contains the Intel Fortran compiler-based Docker container configuration for deploying the NOS workflow on WCOSS2 HPC systems.

## Overview

The `Dockerfile.intel` provides a complete WCOSS2-compatible build environment using Intel oneAPI compilers instead of GNU compilers. This is required for deployment on NOAA's WCOSS2 (Weather and Climate Operational Supercomputing System 2) infrastructure.

## Key Features

- **Intel Fortran Classic (ifort)**: Version 2021.10.0 from Intel oneAPI 2023.2.1
- **Intel C/C++ Classic (icc/icpc)**: Version 2021.10.0
- **Custom OpenMPI Build**: OpenMPI 4.1.6 compiled with Intel compilers for Fortran module compatibility
- **Multi-stage Build**: Optimized builder and runtime stages
- **Full WCOSS2 Compatibility**: All components built with Intel compiler stack

## Container Size

- **Built Image**: 5.43 GB
- **Base OS**: Rocky Linux 9 UBI

## Components Built with Intel Compilers

### Scientific Models
- **ADCIRC** (v56)
  - Serial version (`adcirc`)
  - Parallel MPI version (`padcirc`)
  - Preprocessor (`adcprep`)
  - Built with `-heap-arrays 8192` flag for large array support

- **SCHISM** (v5.10)
  - Standalone build with Intel Fortran + OpenMPI

### Libraries
- **NetCDF-Fortran** 4.6.1 (built from source with ifort)
- **OpenMPI** 4.1.6 (built from source with Intel compilers)
- **NCEP Libraries** (all 7 libraries):
  - bacio
  - w3emc
  - w3nco
  - prod_util
  - ip
  - g2c
  - g2
  - bufr

### STOFS Utilities
All four STOFS preprocessing utilities compiled with ifort:
- `stofs_3d_atl_gen_3Dth_from_hycom`
- `stofs_3d_atl_gen_nudge_from_hycom`
- `stofs_3d_atl_netcdf2shef`
- `stofs_3d_atl_tide_fac`

### Supporting Infrastructure
- **Slurm** 24.11.1.1
- **ecFlow** 5.6.0
- **wgrib2** with GRIB2 support

## Building the Container

### Prerequisites
- Docker or Podman
- 20+ GB free disk space
- Internet connection for downloading sources

### Build Command

```bash
docker build -f containers/Dockerfile.intel -t nos-workflow:intel .
```

### Build Arguments

The following build arguments can be customized:

```bash
docker build -f containers/Dockerfile.intel \
  --build-arg ADCIRC_VERSION=v56 \
  --build-arg SCHISM_VERSION=v5.10.0 \
  --build-arg NETCDF_FORTRAN_VERSION=4.6.1 \
  --build-arg OPENMPI_VERSION=4.1.6 \
  -t nos-workflow:intel .
```

### Build Time
Estimated build time: **30-40 minutes** on modern hardware (8-core CPU)

## Technical Details

### Why Custom OpenMPI?

The system-provided OpenMPI on Rocky Linux 9 is compiled with gfortran, making its Fortran module files (`.mod`) incompatible with Intel Fortran. To resolve this:

1. OpenMPI 4.1.6 is built from source using Intel compilers
2. Installed to `/opt/openmpi`
3. Provides ifort-compatible Fortran MPI modules
4. Enables successful compilation of parallel ADCIRC (`padcirc`) and SCHISM

### Compiler Flags

**Intel Fortran Flags for ADCIRC/SCHISM**:
```
-heap-arrays 8192
```
This flag allocates large arrays on the heap instead of the stack, required for ADCIRC's memory model.

**Intel Fortran Flags for STOFS Utilities**:
```
-O2 -CB -mcmodel=medium -assume byterecl
```
- `-O2`: Optimization level 2
- `-CB`: Enable bounds checking
- `-mcmodel=medium`: Support for large data segments
- `-assume byterecl`: Fortran unformatted I/O compatibility

### Multi-Stage Build

The Dockerfile uses a multi-stage build:

1. **Builder Stage**: Compiles all components with Intel compilers
2. **Runtime Stage (wcoss2)**: Minimal runtime with Intel libraries and binaries

This approach reduces the final image size by ~40%.

## Differences from GNU Compiler Version

| Component | GNU Version | Intel Version |
|-----------|-------------|---------------|
| Fortran Compiler | gfortran 11.x | ifort 2021.10.0 |
| C/C++ Compiler | gcc/g++ 11.x | icc/icpc 2021.10.0 |
| MPI Implementation | System OpenMPI | Custom-built OpenMPI 4.1.6 |
| NetCDF-Fortran | System package | Built from source v4.6.1 |
| Compiler Flags | Standard | WCOSS2-optimized |

## Environment Variables

The container sets the following environment variables:

```bash
PATH=/opt/openmpi/bin:$PATH
LD_LIBRARY_PATH=/opt/openmpi/lib
```

Intel oneAPI compilers are initialized via:
```bash
source /opt/intel/oneapi/compiler/2023.2.1/env/vars.sh
```

## Verification

### Verify Intel Compilers

```bash
docker run --rm nos-workflow:intel bash -c "source /opt/intel/oneapi/compiler/2023.2.1/env/vars.sh && ifort --version"
```

Expected output:
```
ifort (IFORT) 2021.10.0 20230609
```

### Verify OpenMPI

```bash
docker run --rm nos-workflow:intel mpirun --version
```

Expected output:
```
mpirun (Open MPI) 4.1.6
```

### Verify ADCIRC

```bash
docker run --rm nos-workflow:intel ls -lh /opt/models/adcirc/bin/
```

Should show: `adcirc`, `padcirc`, `adcprep`

## Known Issues and Limitations

### WSL2 File Permissions
When building on WSL2, you may encounter git config lock errors. These are due to cross-filesystem permissions between Windows and Linux and don't affect the Docker build.

### Intel Compiler Deprecation Warnings
You may see warnings about Intel C++ Compiler Classic (ICC) being deprecated. This is expected - Intel is transitioning to the new ICX compiler, but ICC is still fully supported in oneAPI 2023.2.1.

### OpenMPI Configuration
The custom OpenMPI build does not include InfiniBand verbs support (`--with-verbs` removed) as it's not needed for containerized environments.

## Repository Structure

```
containers/
├── Dockerfile.intel          # Intel compiler multi-stage build
├── Dockerfile                 # Original GNU compiler build
└── README.intel.md           # This file

sorc/
├── stofs_3d_atl_gen_3Dth_from_hycom.fd/
│   └── makefile              # Updated for ifort
├── stofs_3d_atl_gen_nudge_from_hycom.fd/
│   └── makefile              # Updated for ifort
├── stofs_3d_atl_netcdf2shef.fd/
│   └── makefile              # Updated for ifort
└── stofs_3d_atl_tide_fac.fd/
    └── makefile              # Updated for ifort
```

## Troubleshooting

### Build Fails at OpenMPI Configuration

**Error**: `configure: error: Aborting. Verbs support requested but not found.`

**Solution**: Already fixed in current Dockerfile. The `--with-verbs` flag has been removed.

### ADCIRC MPI Module Not Found

**Error**: `error #7002: Error in opening the compiled module file. Check INCLUDE paths. [MPI]`

**Solution**: Already fixed. OpenMPI is now built with Intel compilers, providing compatible Fortran modules.

### NetCDF-Fortran Module Incompatibility

**Error**: Fortran module version mismatch

**Solution**: Already fixed. NetCDF-Fortran is built from source with ifort instead of using system packages.

## Performance Notes

The Intel compiler stack typically provides:
- **10-20% better performance** for Fortran-heavy scientific codes
- **Better vectorization** for numerical operations
- **Optimizations for Intel architectures** (x86-64)

## License

This Intel compiler configuration maintains compatibility with the existing NOS workflow license structure.

## References

- [Intel oneAPI Documentation](https://www.intel.com/content/www/us/en/developer/tools/oneapi/overview.html)
- [OpenMPI with Intel Compilers](https://www.open-mpi.org/faq/?category=building#build-compilers)
- [ADCIRC Build Instructions](https://github.com/adcirc/adcirc/wiki/Compiling-ADCIRC)
- [WCOSS2 Documentation](https://www.weather.gov/mdl/wcoss2)

## Support

For issues specific to the Intel compiler build:
1. Check this README for known issues
2. Review build logs for specific error messages
3. Verify Intel compiler installation: `ifort --version`
4. Ensure OpenMPI was built correctly: `mpifort --version`

## Changelog

### Version 1.0 (2025-01-19)
- Initial Intel Fortran compiler support
- Custom OpenMPI 4.1.6 build with Intel compilers
- NetCDF-Fortran 4.6.1 from source
- All NCEP libraries with Intel compilers
- ADCIRC v56 with parallel MPI support
- SCHISM v5.10.0 with Intel compilers
- All STOFS utilities updated for ifort
