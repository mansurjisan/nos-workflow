# NOS OFS Unified Workflow Package

This document provides a comprehensive overview of the **NOS OFS Unified Workflow Package**, a framework for running NOAA's Operational Forecast Systems (OFS).

## 1. Introduction: What is this project?

This project is a unified software package designed to configure and execute various operational forecast systems (OFS) developed by the National Ocean Service (NOS), a part of the National Oceanic and Atmospheric Administration (NOAA).

### What are Operational Forecast Systems (OFS)?

OFS are a network of hydrodynamic model systems that provide real-time predictions of oceanographic conditions, including water levels, currents, salinity, and temperature. They are crucial for:

*   **Safe Maritime Navigation:** Providing guidance to commercial and recreational boaters.
*   **Coastal Hazard Preparedness:** Predicting storm surge and coastal flooding.
*   **Ecosystem Management:** Understanding the physical environment that drives coastal ecosystems.

These systems run in operational cycles (typically every 6 hours), generating **nowcasts** (a "hindcast" of the immediate past) and **forecasts** (predictions for the near future, usually 48-120 hours).

This package provides a unified interface to run these complex models, manage their configurations, and process their inputs and outputs in a standardized way.

## 2. Key Concepts and Terminology

The world of operational oceanography is filled with acronyms. Here are some of the key terms you will encounter when working with this package:

| Term | Description |
|---|---|
| **NOAA** | **National Oceanic and Atmospheric Administration**, the US scientific agency responsible for monitoring and forecasting weather, climate, and ocean conditions. |
| **NOS** | **National Ocean Service**, the branch of NOAA that provides science-based solutions to address evolving economic, environmental, and social pressures on our oceans and coasts. |
| **NCO** | **NCEP Central Operations**, the part of NOAA responsible for the operational suite of numerical weather and climate prediction models. |
| **COMF** | **Coastal Ocean Modeling Framework**, a software framework developed by NOS to standardize and streamline the use of operational ocean models. |
| **STOFS** | **Surge and Tide Operational Forecast System**, a specific OFS that provides water level forecasts, particularly for storm surge and tides. |
| **ECFLOW** | A workflow management system used to schedule and run the complex, interdependent tasks that make up an operational forecast cycle. |
| **J-Jobs** | A term referring to the operational jobs run on NCO's systems. |

## 3. Supported Ocean Models

This package supports several different underlying hydrodynamic models. The choice of model depends on the specific geographic region and scientific requirements of the forecast system.

*   **SCHISM (Semi-implicit Cross-scale Hydroscience Integrated System Model):** An unstructured-grid model that is highly flexible and can simulate a wide range of scales, from small creeks to the open ocean, without needing nested grids. It is well-suited for complex coastal areas with intricate shorelines and tidal flats.

*   **ROMS (Regional Ocean Modeling System):** A popular structured-grid model that follows the terrain of the seafloor. It is widely used for a variety of regional oceanographic applications.

*   **FVCOM (Finite Volume Community Ocean Model):** An unstructured-grid model that is particularly well-suited for modeling complex coastlines, estuaries, and areas with wetting and drying (e.g., tidal marshes).

## 4. Project Architecture

The project is organized into the following main directories:

```
nos_ofs/
├── ecf/                          # ECFLOW scripts for workflow management
├── jobs/                         # J-jobs (NCO standard) for different workflow stages
│   ├── JNOS_OFS_PREP             # Unified preparation job
│   ├── JNOS_OFS_NOWCST_FCST      # Unified nowcast/forecast job
│   └── JNOS_OFS_POST             # Unified post-processing job
├── scripts/                      # Ex-scripts (executable scripts)
│   ├── nosofs/                   # COMF-based execution scripts
│   └── stofs_3d_atl/             # STOFS-specific execution scripts
├── ush/                          # Utility scripts and source code
│   ├── nosofs/                   # COMF shell utilities
│   ├── stofs_3d_atl/             # STOFS shell utilities
│   └── python/                   # The core Python package for this framework
├── parm/                         # Configuration files
│   ├── base/                     # Base YAML configurations for each model type
│   └── systems/                  # Specific YAML configurations for each OFS
├── fix/                          # Static input files (e.g., grid files)
└── exec/                         # Compiled model executables
```

## 5. Getting Started: A Quick Tutorial

This tutorial will guide you through the basic steps of using the Python package to manage a forecast system configuration.

### Step 1: Install the Python Package

The core logic of this framework is contained in a Python package located in `ush/python`. It is recommended to install it in editable mode so that any changes you make are immediately available.

```bash
cd nos_ofs/ush/python
pip install -e .
```

### Step 2: List Available Forecast Systems

The package comes pre-configured for several operational systems. You can list them using the command-line interface (CLI):

```bash
python3 -m nos_ofs.cli list
```

This will show you the systems defined in the `parm/systems/` directory.

### Step 3: Configure Your Environment

The shell scripts that run the models rely on a large number of environment variables. The Python package can generate these variables for you from a YAML configuration file.

Choose a system from the list, for example `stofs_3d_atl.yaml`, and use the `export-env` command. You need to specify the `framework` (`stofs` or `comf`) to get the correct variable names.

```bash
# Change to the root directory of the project
cd ../../..

# Export the environment variables
# Note: the 'eval' command executes the output of the python script
eval $(python3 -m nos_ofs.cli export-env --config parm/systems/stofs_3d_atl.yaml --framework stofs)

# You can now inspect the environment variables
echo "OFS system: $OFS"
echo "Grid domain: $LONMIN to $LONMAX"
```

### Step 4: Run a Workflow Step

With the environment configured, you can now run parts of the workflow. The `cli.py` module provides entry points for common tasks like preprocessing.

```bash
# Set the required time variables
export PDY=20250115  #
export cyc=12

# Run the full preprocessing workflow
python3 -m nos_ofs.cli prep --config parm/systems/stofs_3d_atl.yaml
```

This command will orchestrate the necessary steps to prepare the input data for the model run, such as downloading and processing atmospheric and oceanographic forcing data.

## 6. YAML Configuration

The behavior of each forecast system is controlled by YAML files in the `parm/` directory. This provides a clear and version-controllable way to manage model parameters.

*   `parm/base/*.yaml`: These files define the default parameters for each model type (e.g., `schism.yaml`).
*   `parm/systems/*.yaml`: These files define the specific configuration for a particular forecast system (e.g., `stofs_3d_atl.yaml`). They inherit from a base configuration and can override any parameter.

**Example: `stofs_3d_atl.yaml`**
```yaml
_base: schism  # Inherit from the base SCHISM config

system:
  name: stofs_3d_atl
  model_type: schism
  framework: stofs

# Grid dimensions and domain
grid:
  n_nodes: 1813443
  n_elements: 3564104
  n_levels: 51
  domain:
    lon_min: -98.5035
    lon_max: -52.4867
    lat_min: 7.347
    lat_max: 52.5904

# Configuration for different forcing data types
forcing:
  atmospheric:
    primary: gfs  # Use GFS as the primary atmospheric forcing
    hrrr_blend:
      enabled: true
  river:
    primary: nwm  # Use NWM for river forcing
    n_rivers: 7690
  ocean:
    primary: rtofs # Use RTOFS for the ocean boundary

# Control whether to run legacy shell scripts
legacy:
  enabled: true
  scripts:
    gfs: true
    hrrr: true
    river: true
    obc: true
```

## 7. Development

For developers contributing to this package:

### Running Tests

The Python package includes a suite of unit tests.

```bash
cd nos_ofs/ush/python
pytest
```

### Code Style

The code follows the `black` code style and is linted with `flake8`.

```bash
# Format code
black nos_ofs/

# Lint code
flake8 nos_ofs/
```

### Environment Variables for Execution

The package and its associated scripts respect a set of standard environment variables to control execution:

| Variable | Description |
|----------|-------------|
| `OFS_CONFIG` | **Required:** Path to the main YAML config file for the system. |
| `PDY` | Processing date (format: YYYYMMDD). |
| `cyc` | Cycle hour (e.g., 00, 06, 12, 18). |
| `DATA` | The main working directory for the model run. |
| `COMOUT` | The main output directory for final products. |
| `COMINgfs` | Input directory for GFS atmospheric data. |
| `COMINhrrr` | Input directory for HRRR atmospheric data. |
| `COMINnwm` | Input directory for NWM river data. |
| `COMINrtofs` | Input directory for RTOFS ocean boundary data. |

This concludes the overview of the NOS OFS Unified Workflow Package. This new README provides a more detailed introduction for users who may not be familiar with the terminology and concepts of operational oceanography.
