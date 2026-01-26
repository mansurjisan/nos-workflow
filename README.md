# NOS Workflow

[![Docker Build](https://github.com/mansurjisan/nos-workflow/actions/workflows/docker-build.yml/badge.svg)](https://github.com/mansurjisan/nos-workflow/actions/workflows/docker-build.yml)
[![Singularity Build](https://github.com/mansurjisan/nos-workflow/actions/workflows/build-singularity.yml/badge.svg)](https://github.com/mansurjisan/nos-workflow/actions/workflows/build-singularity.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Containerized workflow for NOAA's Surge and Tide Operational Forecast System (STOFS). Pre-built Docker and Singularity containers with ADCIRC, SCHISM, ecFlow, and all dependencies for running on any HPC.

## Quick Start

```bash
# Pull container
singularity pull library://mjisan/nos-workflow/nos-workflow:latest
# or
docker pull mjisan/stofsworkflow:nightly

# Run workflow
singularity exec nos-workflow.sif stofs prep-forecast --config config_schism.yaml
```

## Container Sources

| Source | Location |
|--------|----------|
| Sylabs Cloud | [library://mjisan/nos-workflow/nos-workflow:latest](https://cloud.sylabs.io/library/mjisan/nos-workflow/nos-workflow) |
| Docker Hub | [mjisan/stofsworkflow:nightly](https://hub.docker.com/r/mjisan/stofsworkflow) |
| GitHub Releases | [Download .sif](https://github.com/mansurjisan/nos-workflow/releases/latest) |

## Build from Source

```bash
# Singularity
sudo apptainer build nos-workflow.sif containers/nos-workflow.def

# Docker
docker build -t nos-workflow -f containers/Dockerfile .
```

## Workflows

| Command | Description |
|---------|-------------|
| `stofs prep-nowcast` | Prepare nowcast inputs |
| `stofs nowcast` | Run nowcast model |
| `stofs prep-forecast` | Prepare forecast inputs |
| `stofs forecast` | Run forecast model |
| `stofs post` | Post-processing |

## CI/CD Pipelines

| Platform | Purpose | Trigger |
|----------|---------|---------|
| GitHub Actions | Build & publish containers | Push to main, weekly schedule |
| Jenkins | Integration testing on HPC | Poll SCM (every 5 min) |

## Disclaimer

This repository is a scientific product and is not official communication of the National Oceanic and Atmospheric Administration, or the United States Department of Commerce. All NOAA GitHub project code is provided on an "as is" basis and the user assumes responsibility for its use. Any claims against the Department of Commerce or Department of Commerce bureaus stemming from the use of this GitHub project will be governed by all applicable Federal law. Any reference to specific commercial products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or imply their endorsement, recommendation or favoring by the Department of Commerce. The Department of Commerce seal and logo, or the seal and logo of a DOC bureau, shall not be used in any manner to imply endorsement of any commercial product or activity by DOC or the United States Government.

