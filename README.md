# NOS Workflow

Containerized workflow system for NOAA's Surge and Tide Operational Forecast System (STOFS). This repository provides Docker and Singularity containers with all dependencies pre-installed for running STOFS workflows on any HPC system.

## Features

- **Pre-built Containers**: Docker and Singularity containers with ADCIRC, SCHISM, and all dependencies
- **Portable**: Same container runs on WCOSS2, Hercules, Ursa, ParallelWorks, or any HPC
- **CI/CD Integration**: Automated builds via GitHub Actions and Jenkins
- **Container Registry**: Published to Docker Hub and Sylabs Cloud

## Included Software

| Software | Version | Description |
|----------|---------|-------------|
| ADCIRC | v56.0.3 | ADvanced CIRCulation model |
| SCHISM | v5.11.0 | Semi-implicit Cross-scale Hydroscience Integrated System Model |
| ecFlow | v5.6.0 | ECMWF workflow manager |
| SLURM | v24.11.1.1 | Job scheduler |
| wgrib2 | v3.1.3 | GRIB2 data processor |
| Python | 3.9 | With numpy, netCDF4, xarray, matplotlib |

## Quick Start

### Pull Container

```bash
# Singularity (for HPC)
singularity pull library://mansurjisan/nos-workflow/nos-workflow:latest

# Docker
docker pull mjisan/stofsworkflow:nightly
```

### Run Workflow

```bash
# Singularity
singularity exec nos-workflow.sif stofs prep-forecast --config config_schism.yaml

# Docker
docker run -v /path/to/data:/data mjisan/stofsworkflow:nightly stofs prep-forecast --config config_schism.yaml
```

### Interactive Shell

```bash
# Singularity
singularity shell nos-workflow.sif

# Docker
docker run -it mjisan/stofsworkflow:nightly bash
```

## Container Downloads

| Source | URL |
|--------|-----|
| Sylabs Cloud | `library://mansurjisan/nos-workflow/nos-workflow:latest` |
| Docker Hub | `mjisan/stofsworkflow:nightly` |
| GitHub Releases | [Latest Release](https://github.com/mansurjisan/nos-workflow/releases/latest) |

## Building from Source

### Singularity/Apptainer

```bash
sudo apptainer build nos-workflow.sif containers/nos-workflow.def
```

### Docker

```bash
docker build -t nos-workflow -f containers/Dockerfile .
```

## Repository Structure

```
nos-workflow/
├── containers/
│   ├── Dockerfile              # Docker build file
│   ├── nos-workflow.def        # Singularity definition
│   └── environment.sh          # Runtime environment setup
├── src/                        # Python workflow source code
├── ush/                        # Shell utility scripts
├── scripts/                    # Job scripts
├── examples/                   # Example configurations
├── docs/
│   ├── jenkins-guide.md        # Jenkins CI/CD setup
│   └── hercules-deployment-guide.md  # HPC deployment
├── Jenkinsfile                 # Jenkins pipeline (local)
├── Jenkinsfile.parallelworks   # Jenkins pipeline (ParallelWorks)
└── .github/workflows/
    ├── build-singularity.yml   # Singularity CI/CD
    └── docker-build.yml        # Docker CI/CD
```

## CI/CD Pipelines

### GitHub Actions

- **Singularity Build**: Triggers on push to main/develop, creates GitHub releases, pushes to Sylabs Cloud
- **Docker Build**: Daily builds, pushes to Docker Hub

### Jenkins

- **Local/WSL**: For testing with local data
- **ParallelWorks**: Integration testing on cloud HPC
- **Poll SCM**: Checks for changes every 5 minutes

See [Jenkins Guide](docs/jenkins-guide.md) for setup instructions.

## HPC Deployment

The Singularity container can be deployed to any NOAA HPC:

| HPC | Guide |
|-----|-------|
| Hercules | [Deployment Guide](docs/hercules-deployment-guide.md) |
| WCOSS2 | Coming soon |
| Ursa | Coming soon |

### Basic Deployment

```bash
# Download container
singularity pull library://mansurjisan/nos-workflow/nos-workflow:latest

# Run with data mounts
singularity exec \
    --bind /path/to/gfs:/lfs/h1/ops/prod/com/gfs:ro \
    --bind /path/to/output:/home/wcoss2 \
    nos-workflow.sif stofs prep-forecast --config config_schism.yaml
```

## Workflows

Available workflow commands:

| Command | Description |
|---------|-------------|
| `stofs prep-nowcast` | Prepare nowcast inputs |
| `stofs nowcast` | Run nowcast model |
| `stofs prep-forecast` | Prepare forecast inputs |
| `stofs forecast` | Run forecast model |
| `stofs post` | Post-processing |

## Configuration

Example configuration files are in `examples/`:

- `config_schism.yaml` - SCHISM model configuration
- `config_adcirc.yaml` - ADCIRC model configuration

## Data Requirements

The workflow requires these input datasets:

| Data | Description |
|------|-------------|
| GFS | Global Forecast System atmospheric forcing |
| HRRR | High-Resolution Rapid Refresh (regional) |
| NWM | National Water Model river discharge |
| RTOFS | Real-Time Ocean Forecast System |
| Fix files | Static grid and parameter files |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit changes (`git commit -am 'Add new feature'`)
4. Push to branch (`git push origin feature/my-feature`)
5. Create a Pull Request

## License

See [LICENSE](LICENSE) file for details.

## Contact

- **Issues**: [GitHub Issues](https://github.com/mansurjisan/nos-workflow/issues)
- **Author**: Mansur Jisan

---

#### Disclaimer

This repository is a scientific product and is not official communication of the National Oceanic and Atmospheric Administration, or the United States Department of Commerce. All NOAA GitHub project code is provided on an "as is" basis and the user assumes responsibility for its use. Any claims against the Department of Commerce or Department of Commerce bureaus stemming from the use of this GitHub project will be governed by all applicable Federal law. Any reference to specific commercial products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or imply their endorsement, recommendation or favoring by the Department of Commerce. The Department of Commerce seal and logo, or the seal and logo of a DOC bureau, shall not be used in any manner to imply endorsement of any commercial product or activity by DOC or the United States Government.
