# NOS OFS Orchestration Module

Python orchestration layer for NOS OFS workflows, providing a migration path from shell-based to Python-based workflow management.

## Overview

This module provides Python equivalents of the shell orchestration scripts:

- `nos_ofs_prep_run.sh` → `PrepOrchestrator`
- `nos_ofs_model_run.sh` → `ModelRunOrchestrator`

The Python orchestrators dispatch to the same underlying shell scripts via `subprocess`, ensuring identical behavior while providing better error handling, logging, and programmatic control.

## Architecture

```
orchestration/
├── __init__.py          # Public API
├── prep.py              # PrepOrchestrator
├── model_run.py         # ModelRunOrchestrator
└── handlers/
    ├── __init__.py
    ├── base.py          # Abstract base handlers
    ├── stofs.py         # STOFS-specific handlers
    └── comf.py          # COMF-specific handlers
```

### Framework Dispatch

Both orchestrators auto-detect the framework (STOFS or COMF) from configuration and dispatch to framework-specific handlers:

- **STOFS handlers** call STOFS-specific scripts (e.g., `stofs_3d_atl_create_surface_forcing_gfs.sh`)
- **COMF handlers** call nosofs scripts (e.g., `nos_ofs_create_forcing_met.sh`)

## Prep Workflow

### 7-Step API

The `PrepOrchestrator` provides a unified 7-step interface:

1. **stage_static_files()** - Link/copy grid, control files, static inputs
2. **create_model_config()** - Generate param.nml, run_control.nml, ROMS.in
3. **create_forcing_atmospheric()** - GFS/HRRR (STOFS) or NAM/GFS/RTMA (COMF)
4. **create_forcing_river()** - NWM + St. Lawrence (STOFS) or NWM/USGS (COMF)
5. **create_forcing_obc()** - RTOFS/HYCOM open boundary conditions
6. **create_forcing_nudging()** - T/S interior nudging (optional)
7. **prepare_initial_condition()** - Restart/hotstart file search

### Usage

```python
from nos_ofs.orchestration import PrepOrchestrator
from nos_ofs.config import OFSConfig

# Load configuration
config = OFSConfig.load("stofs_3d_atl")

# Create orchestrator (auto-detects framework)
prep = PrepOrchestrator(config)

# Run all steps
result = prep.run_all()

if result.success:
    print("Prep completed successfully")
    print(result.summary())
else:
    print("Prep failed")
    for error in result.errors:
        print(f"  - {error}")
```

### Individual Steps

```python
# Run individual steps
prep.stage_static_files()
prep.create_model_config()
prep.create_forcing_atmospheric()
prep.create_forcing_river()
prep.create_forcing_obc()
prep.create_forcing_nudging()
prep.prepare_initial_condition()
```

## Model Run Workflow

### 4-Step API (per phase)

The `ModelRunOrchestrator` provides a 4-step interface for each phase:

1. **stage_model_files(phase)** - Copy forcing/static files to $DATA
2. **prepare_restart(phase)** - Find and stage hotstart/initial condition
3. **execute_model(phase)** - Configure runtime and run model via mpiexec
4. **archive_outputs(phase)** - Copy outputs to $COMOUT

### Usage

```python
from nos_ofs.orchestration import ModelRunOrchestrator
from nos_ofs.config import OFSConfig

# Load configuration
config = OFSConfig.load("cbofs")

# Create orchestrator
runner = ModelRunOrchestrator(config)

# Run nowcast
nowcast_result = runner.run_all("nowcast")

if nowcast_result.success:
    # Run forecast
    forecast_result = runner.run_all("forecast")
```

### Individual Steps

```python
# Run individual nowcast steps
runner.stage_model_files("nowcast")
runner.prepare_restart("nowcast")
runner.execute_model("nowcast")
runner.archive_outputs("nowcast")

# Run individual forecast steps
runner.stage_model_files("forecast")
runner.prepare_restart("forecast")
runner.execute_model("forecast")
runner.archive_outputs("forecast")
```

## Result Objects

### StepResult

Individual step execution result:

```python
@dataclass
class StepResult:
    success: bool
    step_name: str
    message: str
    command: str
    stdout: str
    stderr: str
    returncode: int
    duration_seconds: float
    output_files: List[Path]
    errors: List[str]
    warnings: List[str]
    metadata: Dict[str, Any]
```

### PrepResult

Overall prep workflow result:

```python
@dataclass
class PrepResult:
    success: bool
    total_duration_seconds: float
    step_results: Dict[str, StepResult]
    errors: List[str]
    warnings: List[str]
```

### ModelRunResult

Overall model run result:

```python
@dataclass
class ModelRunResult:
    success: bool
    phase: str
    total_duration_seconds: float
    step_results: Dict[str, StepResult]
    errors: List[str]
    warnings: List[str]
```

## Error Handling

### Fail-Fast vs. Continue-On-Error

```python
# Stop on first failure (default)
result = prep.run_all(fail_fast=True)

# Continue and collect all errors
result = prep.run_all(fail_fast=False)
for step_name, step_result in result.step_results.items():
    if not step_result.success:
        print(f"{step_name} failed: {step_result.message}")
```

### Fatal vs. Non-Fatal Steps

Some steps are non-fatal (e.g., nudging forcing):

- **Fatal steps**: Atmospheric, river, OBC forcing → workflow stops on failure
- **Non-fatal steps**: Nudging forcing → warning logged, workflow continues

## Logging

The orchestrators use Python's standard `logging` module:

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Run workflow
prep = PrepOrchestrator(config)
result = prep.run_all()
```

## Framework-Specific Handlers

### STOFS Handlers

**STOFSPrepHandler** calls:
- `stofs_3d_atl_create_param_nml.sh`
- `stofs_3d_atl_create_bctides_in.sh`
- `stofs_3d_atl_create_surface_forcing_gfs.sh`
- `stofs_3d_atl_create_surface_forcing_hrrr.sh`
- `stofs_3d_atl_create_river_forcing_nwm.sh`
- `stofs_3d_atl_create_river_st_lawrence.sh`
- `stofs_3d_atl_create_obc_3d_th.sh`
- `stofs_3d_atl_create_obc_nudge.sh`

**STOFSModelRunHandler** orchestrates:
- File staging from `COMOUTrerun`
- Hotstart search (previous cycle or coldstart)
- SCHISM execution via `mpiexec`
- Combined hotstart creation and archival

### COMF Handlers

**COMFPrepHandler** calls:
- `nos_ofs_launch.sh` (setup & file staging)
- `nos_ofs_prep_*_ctl.sh` (model control files)
- `nos_ofs_create_forcing_met.sh` (atmospheric forcing)
- `nos_ofs_create_forcing_river.sh` (river forcing)
- `nos_ofs_create_forcing_obc.sh` (ocean boundary)
- `nos_ofs_create_forcing_nudg.sh` (interior nudging)

**COMFModelRunHandler** calls:
- `nos_ofs_launch.sh` (file staging)
- `nos_ofs_nowcast_forecast.sh` (model execution)
- `nos_ofs_archive.sh` (output archival)

## Environment Variables

The orchestrators pass the current environment (`os.environ`) to subprocess calls, plus any framework-specific overrides. Key variables:

- `OFS_FRAMEWORK` - "stofs" or "comf"
- `DATA` - Working directory
- `COMOUT` - Output directory
- `COMOUTrerun` - Intermediate output directory
- `USHnos`, `USHstofs3d` - Utility script directories
- `FIXnos`, `FIXstofs3d` - Fix file directories
- `EXECnos`, `EXECstofs3d` - Executable directories

## Migration Path

This orchestration layer provides a phased migration from shell to Python:

### Phase A (Current)
Shell scripts call Python for configuration:
```bash
eval $(python3 -m nos_ofs.utils.yaml_to_env ${STOFS_CONFIG} --section domain)
```

### Phase B (This Module)
Python orchestrates shell scripts:
```python
prep = PrepOrchestrator(config)
result = prep.run_all()  # Calls shell scripts via subprocess
```

### Phase C (Future)
Native Python forcing processors:
```python
from nos_ofs.forcing import GFSProcessor, RTOFSProcessor, NWMProcessor

gfs = GFSProcessor(config, grid)
result = gfs.process()  # Pure Python, no subprocess
```

## Examples

See `examples/orchestration_demo.py` for a complete demo script.

```bash
# Run prep for STOFS-3D Atlantic
python orchestration_demo.py --ofs stofs_3d_atl --phase prep

# Run nowcast for CBOFS
python orchestration_demo.py --ofs cbofs --phase nowcast

# Run forecast for CBOFS
python orchestration_demo.py --ofs cbofs --phase forecast
```

## Testing

```python
import pytest
from nos_ofs.orchestration import PrepOrchestrator
from nos_ofs.config import OFSConfig

def test_prep_orchestrator():
    config = OFSConfig.from_environment()
    config.RUN = "stofs_3d_atl"

    prep = PrepOrchestrator(config, framework="stofs")

    # Test individual step
    result = prep.stage_static_files()
    assert result.success

    # Test full workflow
    result = prep.run_all()
    assert result.success
```

## See Also

- Shell orchestration: `ush/nos_ofs_prep_run.sh`, `ush/nos_ofs_model_run.sh`
- STOFS scripts: `ush/stofs_3d_atl/`
- COMF scripts: `ush/nos_ofs_*.sh`
- Configuration: `nos_ofs/config/`
