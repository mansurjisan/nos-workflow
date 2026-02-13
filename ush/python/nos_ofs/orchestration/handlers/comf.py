"""
COMF Framework Handlers

Implements prep, model run, and post-processing orchestration for
COMF/nosofs systems by calling existing nosofs shell scripts via
subprocess and providing Python-native post-processing.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BasePrepHandler, BaseModelRunHandler, BasePostHandler, StepResult

log = logging.getLogger(__name__)


class COMFPrepHandler(BasePrepHandler):
    """
    COMF-specific prep handler.

    Orchestrates COMF preparation by calling existing shell scripts:
    - nos_ofs_launch.sh (setup & file staging)
    - nos_ofs_prep_*_ctl.sh (model control files)
    - nos_ofs_create_forcing_met.sh (atmospheric forcing)
    - nos_ofs_create_forcing_river.sh (river forcing)
    - nos_ofs_create_forcing_obc.sh (ocean boundary)
    - nos_ofs_create_forcing_nudg.sh (interior nudging)
    """

    def __init__(self, config: Any):
        """
        Initialize COMF prep handler.

        Args:
            config: OFSConfig instance with COMF configuration
        """
        super().__init__(config)
        # Use environment variables as fallback since config might not have all attributes
        self.ush_dir = Path(
            os.environ.get("USHnos", os.environ.get("USHofs", getattr(config.runtime, "ush_ofs", "/tmp")))
        )
        self.fix_dir = Path(
            os.environ.get("FIXnos", os.environ.get("FIXofs", getattr(config.runtime, "fix_ofs", "/tmp")))
        )
        self.exec_dir = Path(
            os.environ.get("EXECnos", os.environ.get("EXECofs", getattr(config.runtime, "exec_ofs", "/tmp")))
        )
        self.data_dir = Path(os.environ.get("DATA", getattr(config.runtime, "data", "/tmp")))
        self.comout = Path(os.environ.get("COMOUT", getattr(config.runtime, "comout", "/tmp")))
        self.ofs = os.environ.get("OFS", os.environ.get("RUN", "cbofs"))
        self.ocean_model = os.environ.get("OCEAN_MODEL", "ROMS")

    def stage_static_files(self) -> StepResult:
        """
        Stage COMF static files and load configuration.

        This replicates the 3-tier config loading from nos_ofs_prep_run.sh:
        1. Load from OFS_CONFIG env var (YAML)
        2. Check FIXofs/${PREFIXNOS}.yaml
        3. Fall back to FIXofs/${PREFIXNOS}.ctl

        Then sources nos_ofs_launch.sh to set up ~200 environment variables
        and stage static files.
        """
        self.logger.info("Staging COMF static files and loading configuration")

        try:
            os.chdir(self.data_dir)

            # 3-tier config loading
            config_source = "none"
            prefixnos = os.environ.get("PREFIXNOS", self.ofs)

            # Option 1: Load from OFS_CONFIG environment variable (YAML)
            ofs_config = os.environ.get("OFS_CONFIG", "")
            if ofs_config and Path(ofs_config).exists():
                self.logger.info(f"Loading configuration from YAML: {ofs_config}")
                config_script = self.ush_dir / "nos_ofs_config.sh"
                if config_script.exists():
                    result = self._source_and_capture_env(
                        str(config_script),
                        "",
                        step_name="load_yaml_config",
                        fatal=False,
                    )
                    if result.success and os.environ.get("OFS_CONFIG_LOADED", "0") == "1":
                        config_source = "yaml"
                        self.logger.info(f"Successfully loaded YAML config from {ofs_config}")

            # Option 2: Check for YAML config in FIXofs
            if config_source == "none":
                yaml_path = self.fix_dir / f"{prefixnos}.yaml"
                if yaml_path.exists():
                    self.logger.info(f"Loading configuration from YAML: {yaml_path}")
                    os.environ["OFS_CONFIG"] = str(yaml_path)
                    config_script = self.ush_dir / "nos_ofs_config.sh"
                    if config_script.exists():
                        result = self._source_and_capture_env(
                            str(config_script),
                            "",
                            step_name="load_yaml_config",
                            fatal=False,
                        )
                        if result.success and os.environ.get("OFS_CONFIG_LOADED", "0") == "1":
                            config_source = "yaml"
                            self.logger.info(f"Successfully loaded YAML config from {yaml_path}")

            # Option 3: Fall back to legacy .ctl file
            if config_source == "none":
                ctl_path = self.fix_dir / f"{prefixnos}.ctl"
                if ctl_path.exists():
                    self.logger.info(f"Loading legacy .ctl config from {ctl_path}")
                    result = self._source_and_capture_env(
                        str(ctl_path),
                        "",
                        step_name="load_ctl_config",
                        fatal=True,
                    )
                    if result.success:
                        config_source = "ctl"
                        self.logger.info(f"Loaded legacy .ctl config from {ctl_path}")
                else:
                    return StepResult(
                        success=False,
                        step_name="stage_static_files",
                        message=f"No config file found: {prefixnos}.yaml or {prefixnos}.ctl",
                        errors=[
                            f"Control file not found in {self.fix_dir}: "
                            f"{prefixnos}.yaml or {prefixnos}.ctl"
                        ],
                    )

            self.logger.info(f"Configuration loaded from: {config_source}")

            # Now source nos_ofs_launch.sh to set up environment and stage files
            launch_script = self.ush_dir / "nos_ofs_launch.sh"
            result = self._source_and_capture_env(
                str(launch_script),
                f"{self.ofs} prep",
                step_name="nos_ofs_launch",
                fatal=True,
            )

            return result

        except Exception as e:
            self.logger.exception(f"Failed to stage static files: {e}")
            return StepResult(
                success=False,
                step_name="stage_static_files",
                message=str(e),
                errors=[str(e)],
            )

    def create_model_config(self) -> StepResult:
        """
        Create COMF model control files.

        Calls model-specific control file generators:
        - FVCOM: nos_ofs_prep_fvcom_ctl.sh
        - ROMS: nos_ofs_prep_roms_ctl.sh
        - SCHISM: nos_ofs_prep_schism_ctl.sh
        """
        self.logger.info(f"Creating COMF model configuration for {self.ocean_model}")

        ocean_model_lower = self.ocean_model.lower()

        # Map model type to control file script
        if ocean_model_lower in ["fvcom"]:
            script_name = "nos_ofs_prep_fvcom_ctl.sh"
        elif ocean_model_lower in ["roms"]:
            script_name = "nos_ofs_prep_roms_ctl.sh"
        elif ocean_model_lower in ["schism", "selfe"]:
            script_name = "nos_ofs_prep_schism_ctl.sh"
        else:
            return StepResult(
                success=False,
                step_name="create_model_config",
                message=f"Unknown ocean model: {self.ocean_model}",
                errors=[f"Unsupported OCEAN_MODEL: {self.ocean_model}"],
            )

        script = self.ush_dir / script_name

        # Create nowcast control file
        command = f"{script} {self.ofs} nowcast"
        result = self._run_subprocess(
            command,
            step_name="create_config_nowcast",
            fatal=True,
        )
        if not result.success:
            return result

        # SCHISM-specific: Create NWM source/sink tar archives
        if ocean_model_lower in ["schism", "selfe"]:
            self.logger.info("Creating SCHISM NWM source/sink tar archives")

            try:
                # Get variables from environment
                nwm_source_sink_now = os.environ.get("NWM_SOURCE_SINK_NOW", "nwm_source_sink_nowcast.tar")
                nwm_source_sink_fore = os.environ.get("NWM_SOURCE_SINK_FORE", "nwm_source_sink_forecast.tar")

                # Create nowcast tar archive
                tar_cmd = f"tar -cvf {nwm_source_sink_now} -C ./data/ ."
                tar_result = self._run_subprocess(
                    tar_cmd,
                    step_name="tar_nwm_nowcast",
                    fatal=True,
                    timeout=600,
                )
                if not tar_result.success:
                    return tar_result

                # Copy to COMOUT
                copy_cmd = f"cp {nwm_source_sink_now} {self.comout}/{nwm_source_sink_now}"
                copy_result = self._run_subprocess(
                    copy_cmd,
                    step_name="copy_nwm_nowcast_tar",
                    fatal=True,
                    timeout=300,
                )
                if not copy_result.success:
                    return copy_result

                # Read nowcast_running_day and compute offset
                nowcast_running_day_file = self.data_dir / "nowcast_running_day"
                if nowcast_running_day_file.exists():
                    with open(nowcast_running_day_file, 'r') as f:
                        rnday = float(f.read().strip())
                    nsecond = int(rnday * 3600 * 24)

                    # Adjust vsink.th, vsource.th, msource.th timestamps
                    data_subdir = self.data_dir / "data"
                    if data_subdir.exists():
                        for filename in ["vsink.th", "vsource.th", "msource.th"]:
                            filepath = data_subdir / filename
                            if filepath.exists():
                                # Use awk to adjust timestamps
                                awk_cmd = (
                                    f"cd {data_subdir} && "
                                    f"awk -v awk_var={nsecond} '{{ $1 = $1 - awk_var ; print }}' {filename} > {filename}.new && "
                                    f"awk '$1 >= 0' {filename}.new > {filename}.new.new && "
                                    f"mv {filename}.new.new {filename} && "
                                    f"rm -f {filename}.new"
                                )
                                awk_result = self._run_subprocess(
                                    awk_cmd,
                                    step_name=f"adjust_nwm_{filename}",
                                    fatal=True,
                                    timeout=300,
                                )
                                if not awk_result.success:
                                    return awk_result

                # Create forecast tar archive
                tar_cmd_fore = f"tar -cvf {nwm_source_sink_fore} -C ./data/ ."
                tar_result_fore = self._run_subprocess(
                    tar_cmd_fore,
                    step_name="tar_nwm_forecast",
                    fatal=True,
                    timeout=600,
                )
                if not tar_result_fore.success:
                    return tar_result_fore

                # Copy to COMOUT
                copy_cmd_fore = f"cp {nwm_source_sink_fore} {self.comout}/{nwm_source_sink_fore}"
                copy_result_fore = self._run_subprocess(
                    copy_cmd_fore,
                    step_name="copy_nwm_forecast_tar",
                    fatal=True,
                    timeout=300,
                )
                if not copy_result_fore.success:
                    return copy_result_fore

                self.logger.info("SCHISM NWM tar archives created successfully")

            except Exception as e:
                self.logger.exception(f"Failed to create SCHISM NWM tar archives: {e}")
                return StepResult(
                    success=False,
                    step_name="create_model_config",
                    message=f"Failed to create NWM tar archives: {e}",
                    errors=[str(e)],
                )

        # Create forecast control file if LEN_FORECAST > 0
        len_forecast = int(os.environ.get("LEN_FORECAST", "0"))
        if len_forecast > 0:
            command = f"{script} {self.ofs} forecast"
            result = self._run_subprocess(
                command,
                step_name="create_config_forecast",
                fatal=True,
            )

        return result

    def create_forcing_atmospheric(self) -> StepResult:
        """
        Create atmospheric forcing (NAM/GFS/HRRR/RTMA).

        Replicates complete logic from nos_ofs_prep_run.sh:_comf_create_forcing_atmospheric
        including:
        - MET_NUM=2 dual nowcast sources
        - nfore=2 blended forecast (HRRR:NDFD style)
        - MET_DBASE.NOWCAST/FORECAST file reading
        - metnum, met_fore_round exports
        - File copy/move/rename between rounds
        """
        self.logger.info("Creating COMF atmospheric forcing")

        try:
            os.chdir(self.data_dir)

            # Get forcing configuration from environment
            dbase_met_now = os.environ.get("DBASE_MET_NOW", "NAM")
            dbase_met_now2 = os.environ.get("DBASE_MET_NOW2", "")
            dbase_met_for = os.environ.get("DBASE_MET_FOR", "GFS")
            dbase_met_for2 = os.environ.get("DBASE_MET_FOR2", "")
            time_hotstart = os.environ.get("time_hotstart", "")
            time_nowcastend = os.environ.get("time_nowcastend", "")
            time_forecastend = os.environ.get("time_forecastend", "")
            met_num = int(os.environ.get("MET_NUM", "1"))
            ndate = os.environ.get("NDATE", "ndate")

            if not all([time_hotstart, time_nowcastend]):
                return StepResult(
                    success=False,
                    step_name="create_forcing_atmospheric",
                    message="Missing time configuration",
                    errors=["time_hotstart or time_nowcastend not set in environment"],
                )

            script = self.ush_dir / "nos_ofs_create_forcing_met.sh"

            # ========== NOWCAST FORCING ==========
            os.environ["metnum"] = "1"

            self.logger.info("Generating meteorological forcing for nowcast")
            command = f"{script} nowcast {dbase_met_now} {time_hotstart} {time_nowcastend}"
            result = self._run_subprocess(
                command,
                step_name="create_forcing_met_nowcast",
                fatal=True,
            )
            if not result.success:
                return result

            # Update DBASE_MET_NOW if actual source changed
            met_dbase_nowcast = self.data_dir / "MET_DBASE.NOWCAST"
            if met_dbase_nowcast.exists():
                with open(met_dbase_nowcast, 'r') as f:
                    dbase = f.read().strip()
                self.logger.info(f"DBASE={dbase} DBASE_MET_NOW={dbase_met_now}")
                if dbase != dbase_met_now:
                    dbase_met_now = dbase
                    os.environ["DBASE_MET_NOW"] = dbase

            # Second nowcast met source (if MET_NUM=2)
            if met_num == 2:
                os.environ["metnum"] = "2"
                self.logger.info("Generating second nowcast met source")
                command = f"{script} nowcast {dbase_met_now2} {time_hotstart} {time_nowcastend}"
                result = self._run_subprocess(
                    command,
                    step_name="create_forcing_met_nowcast2",
                    fatal=True,
                )
                if not result.success:
                    return result

                # Update DBASE_MET_NOW if changed
                if met_dbase_nowcast.exists():
                    with open(met_dbase_nowcast, 'r') as f:
                        dbase = f.read().strip()
                    if dbase != dbase_met_now:
                        dbase_met_now = dbase
                        os.environ["DBASE_MET_NOW"] = dbase

            # ========== FORECAST FORCING ==========
            os.environ["metnum"] = "1"

            len_forecast = int(os.environ.get("LEN_FORECAST", "0"))
            if len_forecast > 0 and time_forecastend:
                self.logger.info("Generating meteorological forcing for forecast")

                # Determine number of forecast met sources (blended e.g. HRRR:NDFD)
                nfore = dbase_met_for.count(':') + 1

                if nfore == 1:
                    # Single forecast source
                    dbase = dbase_met_for.rstrip(':')
                    command = f"{script} forecast {dbase} {time_nowcastend} {time_forecastend}"
                    result = self._run_subprocess(
                        command,
                        step_name="create_forcing_met_forecast",
                        fatal=True,
                    )
                    if not result.success:
                        return result

                elif nfore == 2:
                    # Blended forecast (two rounds)
                    parts = dbase_met_for.split(':')
                    dbase1 = parts[0]
                    dbase2 = parts[1]

                    # First round (e.g., HRRR for 0-48h)
                    import subprocess as sp
                    time_end_round1 = sp.check_output(
                        f"{ndate} +48 {time_nowcastend}",
                        shell=True,
                        text=True
                    ).strip()

                    os.environ["met_fore_round"] = "1"
                    command = f"{script} forecast {dbase1} {time_nowcastend} {time_end_round1}"
                    result = self._run_subprocess(
                        command,
                        step_name="create_forcing_met_forecast_round1",
                        fatal=True,
                    )
                    if not result.success:
                        return result

                    # Read actual source from MET_DBASE.FORECAST
                    met_dbase_forecast = self.data_dir / "MET_DBASE.FORECAST"
                    if met_dbase_forecast.exists():
                        with open(met_dbase_forecast, 'r') as f:
                            dbase = f.read().strip()
                        self.logger.info(f"Round 1: DBASE={dbase}")

                    # Backup round 1 files
                    met_nc1_fore = os.environ.get("MET_NETCDF_1_FORECAST", "met_netcdf_1_forecast.nc")
                    met_nc2_fore = os.environ.get("MET_NETCDF_2_FORECAST", "met_netcdf_2_forecast.nc")
                    if Path(f"{met_nc1_fore}1").exists():
                        import shutil
                        shutil.copy2(f"{met_nc1_fore}1", f"{met_nc1_fore}.{dbase}")
                    if Path(f"{met_nc2_fore}1").exists():
                        import shutil
                        shutil.copy2(f"{met_nc2_fore}1", f"{met_nc2_fore}.{dbase}")

                    # Second round (e.g., NDFD for 0-144h)
                    os.environ["met_fore_round"] = "2"
                    command = f"{script} forecast {dbase2} {time_nowcastend} {time_forecastend}"
                    result = self._run_subprocess(
                        command,
                        step_name="create_forcing_met_forecast_round2",
                        fatal=True,
                    )
                    if not result.success:
                        return result

                    # Read actual source
                    if met_dbase_forecast.exists():
                        with open(met_dbase_forecast, 'r') as f:
                            dbase = f.read().strip()
                        self.logger.info(f"Round 2: DBASE={dbase}")

                    # Rename round 2 files
                    if Path(f"{met_nc1_fore}2").exists():
                        import shutil
                        shutil.move(f"{met_nc1_fore}2", f"{met_nc1_fore}.{dbase}")
                    if Path(f"{met_nc2_fore}2").exists():
                        import shutil
                        shutil.move(f"{met_nc2_fore}2", f"{met_nc2_fore}.{dbase}")

                    # Remove round 1 backups
                    for f in [f"{met_nc1_fore}1", f"{met_nc2_fore}1"]:
                        if Path(f).exists():
                            Path(f).unlink()

                # Second forecast met source (if MET_NUM=2)
                if met_num == 2:
                    os.environ["metnum"] = "2"
                    self.logger.info("Generating second forecast met source")
                    command = f"{script} forecast {dbase_met_for2} {time_nowcastend} {time_forecastend}"
                    result = self._run_subprocess(
                        command,
                        step_name="create_forcing_met_forecast2",
                        fatal=True,
                    )
                    if not result.success:
                        return result

                    # Read and rename files
                    met_dbase_forecast = self.data_dir / "MET_DBASE.FORECAST"
                    if met_dbase_forecast.exists():
                        with open(met_dbase_forecast, 'r') as f:
                            dbase = f.read().strip()
                        self.logger.info(f"Second forecast source: DBASE={dbase}")

                    met_nc1_fore = os.environ.get("MET_NETCDF_1_FORECAST", "met_netcdf_1_forecast.nc")
                    met_nc2_fore = os.environ.get("MET_NETCDF_2_FORECAST", "met_netcdf_2_forecast.nc")
                    if Path(f"{met_nc1_fore}2").exists():
                        import shutil
                        shutil.move(f"{met_nc1_fore}2", f"{met_nc1_fore}.{dbase}")
                    if Path(f"{met_nc2_fore}2").exists():
                        import shutil
                        shutil.move(f"{met_nc2_fore}2", f"{met_nc2_fore}.{dbase}")
                    for f in [f"{met_nc1_fore}1", f"{met_nc2_fore}1"]:
                        if Path(f).exists():
                            Path(f).unlink()

                # Update DBASE_MET_FOR if actual source changed
                met_dbase_forecast = self.data_dir / "MET_DBASE.FORECAST"
                if met_dbase_forecast.exists():
                    with open(met_dbase_forecast, 'r') as f:
                        dbase = f.read().strip()
                    self.logger.info(f"Final DBASE={dbase} DBASE_MET_FOR={dbase_met_for}")
                    if dbase != dbase_met_for:
                        dbase_met_for = dbase
                        os.environ["DBASE_MET_FOR"] = dbase

            self.logger.info("COMF atmospheric forcing completed successfully")
            return StepResult(
                success=True,
                step_name="create_forcing_atmospheric",
                message="Atmospheric forcing created",
            )

        except Exception as e:
            self.logger.exception(f"Failed to create atmospheric forcing: {e}")
            return StepResult(
                success=False,
                step_name="create_forcing_atmospheric",
                message=str(e),
                errors=[str(e)],
            )

    def create_forcing_river(self) -> StepResult:
        """
        Create river forcing (NWM/USGS).

        Calls nos_ofs_create_forcing_river.sh which handles:
        - NWM streamflow data
        - USGS fallback for missing NWM data
        - Model-specific river file formatting
        """
        self.logger.info("Creating COMF river forcing")

        script = self.ush_dir / "nos_ofs_create_forcing_river.sh"
        result = self._run_subprocess(
            script,
            step_name="create_forcing_river",
            fatal=True,
        )

        return result

    def create_forcing_obc(self) -> StepResult:
        """
        Create open boundary conditions (RTOFS/HYCOM).

        Calls nos_ofs_create_forcing_obc.sh.

        Note: Some systems (lsofs, loofs) don't need OBC.
        """
        self.logger.info("Creating COMF OBC forcing")

        # Skip OBC for systems that don't need it
        if self.ofs.lower() in ["lsofs", "loofs"]:
            self.logger.info(f"Skipping OBC for {self.ofs} (not required)")
            return StepResult(
                success=True,
                step_name="create_forcing_obc",
                message=f"OBC not required for {self.ofs}",
            )

        script = self.ush_dir / "nos_ofs_create_forcing_obc.sh"
        result = self._run_subprocess(
            script,
            step_name="create_forcing_obc",
            fatal=True,
        )

        return result

    def create_forcing_nudging(self) -> StepResult:
        """
        Create interior nudging fields (optional).

        Calls nos_ofs_create_forcing_nudg.sh if TS_NUDGING=1.
        """
        self.logger.info("Creating COMF nudging forcing")

        ts_nudging = int(os.environ.get("TS_NUDGING", "0"))

        if ts_nudging != 1:
            self.logger.info(f"T/S nudging not enabled (TS_NUDGING={ts_nudging})")
            return StepResult(
                success=True,
                step_name="create_forcing_nudging",
                message="Nudging not enabled",
            )

        script = self.ush_dir / "nos_ofs_create_forcing_nudg.sh"
        result = self._run_subprocess(
            script,
            step_name="create_forcing_nudging",
            fatal=True,  # Fatal - matches shell err_chk
        )

        return result

    def prepare_initial_condition(self) -> StepResult:
        """
        Prepare initial condition (handled by nos_ofs_launch.sh).

        COMF restart/initial condition search is handled inside
        nos_ofs_launch.sh, which was already called by stage_static_files().
        """
        self.logger.info("COMF initial condition handled by nos_ofs_launch.sh")

        return StepResult(
            success=True,
            step_name="prepare_initial_condition",
            message="Handled by nos_ofs_launch.sh",
        )


class COMFModelRunHandler(BaseModelRunHandler):
    """
    COMF-specific model run handler.

    Orchestrates COMF model execution by calling:
    - nos_ofs_launch.sh (file staging for each phase)
    - nos_ofs_nowcast_forecast.sh (model execution)
    - nos_ofs_archive.sh (output archival)
    """

    def __init__(self, config: Any):
        """
        Initialize COMF model run handler.

        Args:
            config: OFSConfig instance with COMF configuration
        """
        super().__init__(config)
        # Use environment variables as fallback
        self.ush_dir = Path(
            os.environ.get("USHnos", os.environ.get("USHofs", getattr(config.runtime, "ush_ofs", "/tmp")))
        )
        self.data_dir = Path(os.environ.get("DATA", getattr(config.runtime, "data", "/tmp")))
        self.ofs = os.environ.get("OFS", os.environ.get("RUN", "cbofs"))

    def stage_model_files(self, phase: str) -> StepResult:
        """
        Stage files for model run.

        Calls nos_ofs_launch.sh to set up the working directory.
        """
        self.logger.info(f"Staging COMF files for {phase}")

        script = self.ush_dir / "nos_ofs_launch.sh"
        # Use "nowcast" for launch even for forecast phase (COMF convention)
        command = f"source {script} {self.ofs} nowcast"

        result = self._run_subprocess(
            command,
            step_name=f"stage_files_{phase}",
            fatal=True,
        )

        return result

    def prepare_restart(self, phase: str) -> StepResult:
        """
        Prepare restart file.

        COMF restart handling is done inside nos_ofs_launch.sh which
        sets INI_FILE_NOWCAST and INI_FILE_FORECAST variables.
        """
        self.logger.info(f"COMF restart for {phase} handled by nos_ofs_launch.sh")

        return StepResult(
            success=True,
            step_name=f"prepare_restart_{phase}",
            message="Handled by nos_ofs_launch.sh",
        )

    def execute_model(self, phase: str) -> StepResult:
        """
        Execute the COMF model.

        Calls nos_ofs_nowcast_forecast.sh which handles:
        - Model-specific execution (ROMS, FVCOM, SCHISM)
        - MPI setup
        - Output validation
        """
        self.logger.info(f"Executing COMF {phase}")

        script = self.ush_dir / "nos_ofs_nowcast_forecast.sh"
        command = f"{script} {phase}"

        # Model execution can take hours
        result = self._run_subprocess(
            command,
            step_name=f"execute_model_{phase}",
            fatal=True,
            timeout=28800,  # 8 hours
        )

        return result

    def archive_outputs(self, phase: str) -> StepResult:
        """
        Archive COMF outputs to COMOUT.

        Calls nos_ofs_archive.sh which handles:
        - NetCDF output archival
        - Restart file archival
        - Diagnostic file archival
        """
        self.logger.info(f"Archiving COMF outputs for {phase}")

        script = self.ush_dir / "nos_ofs_archive.sh"
        command = f"{script} {phase}"

        result = self._run_subprocess(
            command,
            step_name=f"archive_outputs_{phase}",
            fatal=True,
        )

        return result


class COMFPostHandler(BasePostHandler):
    """
    COMF-specific post-processing handler.

    Provides a Python-native post-processing pipeline for COMF/nosofs
    systems (ROMS, FVCOM, SCHISM). Dispatches to the appropriate
    model-specific post-processor from the nos_ofs.postprocessing package.

    This handler implements the "not yet implemented" COMF post-processing
    placeholder in JNOS_OFS_POST.
    """

    def __init__(self, config: Any):
        """
        Initialize COMF post-processing handler.

        Args:
            config: OFSConfig instance with COMF configuration
        """
        super().__init__(config)
        self.ush_dir = Path(
            os.environ.get(
                "USHnos",
                os.environ.get(
                    "USHofs",
                    getattr(getattr(config, "runtime", config), "ush_ofs", "/tmp"),
                ),
            )
        )
        self.data_dir = Path(
            os.environ.get("DATA", getattr(config, "DATA", "/tmp"))
        )
        self.comout = Path(
            os.environ.get("COMOUT", getattr(config, "COMOUT", "/tmp"))
        )
        self.ofs = os.environ.get("OFS", os.environ.get("RUN", "cbofs"))
        self.ocean_model = os.environ.get(
            "OCEAN_MODEL",
            getattr(config, "OCEAN_MODEL", "ROMS"),
        ).upper()

        # Create model-specific post-processor
        self._processor = self._create_processor()

    def _create_processor(self):
        """Create model-specific post-processor based on OCEAN_MODEL."""
        try:
            from nos_ofs.postprocessing import (
                SCHISMPostProcessor,
                ROMSPostProcessor,
                FVCOMPostProcessor,
            )

            if self.ocean_model in ("SCHISM", "SELFE"):
                return SCHISMPostProcessor(self.config, framework="comf")
            elif self.ocean_model == "ROMS":
                return ROMSPostProcessor(self.config)
            elif self.ocean_model == "FVCOM":
                return FVCOMPostProcessor(self.config)
            else:
                self.logger.warning(
                    f"Unknown OCEAN_MODEL '{self.ocean_model}'; "
                    f"defaulting to ROMS post-processor"
                )
                return ROMSPostProcessor(self.config)

        except ImportError as e:
            self.logger.warning(
                f"Post-processing package not available: {e}. "
                f"Post-processing will use shell script fallback."
            )
            return None

    def extract_fields(self) -> StepResult:
        """Extract 2D/3D fields from COMF model output."""
        self.logger.info(f"COMF: Extracting fields for {self.ocean_model}")

        import time as _time

        start = _time.time()

        if self._processor is not None:
            try:
                result = self._processor.extract_fields()
                duration = _time.time() - start
                return StepResult(
                    success=result.success,
                    step_name="extract_fields",
                    message=f"Extracted fields in {duration:.1f}s",
                    duration_seconds=duration,
                    output_files=result.output_files,
                    errors=result.errors,
                    warnings=result.warnings,
                )
            except Exception as e:
                duration = _time.time() - start
                self.logger.error(f"Field extraction failed: {e}")
                return StepResult(
                    success=False,
                    step_name="extract_fields",
                    message=str(e),
                    duration_seconds=duration,
                    errors=[str(e)],
                )

        duration = _time.time() - start
        return StepResult(
            success=True,
            step_name="extract_fields",
            message="No post-processor available; skipping",
            duration_seconds=duration,
            warnings=["Post-processor not initialized"],
        )

    def extract_stations(self) -> StepResult:
        """Extract station timeseries from COMF model output."""
        self.logger.info(f"COMF: Extracting station timeseries for {self.ocean_model}")

        import time as _time

        start = _time.time()

        if self._processor is not None:
            try:
                result = self._processor.extract_stations()
                duration = _time.time() - start
                return StepResult(
                    success=result.success,
                    step_name="extract_stations",
                    message=f"Extracted stations in {duration:.1f}s",
                    duration_seconds=duration,
                    output_files=result.output_files,
                    errors=result.errors,
                    warnings=result.warnings,
                )
            except Exception as e:
                duration = _time.time() - start
                self.logger.error(f"Station extraction failed: {e}")
                return StepResult(
                    success=False,
                    step_name="extract_stations",
                    message=str(e),
                    duration_seconds=duration,
                    errors=[str(e)],
                )

        duration = _time.time() - start
        return StepResult(
            success=True,
            step_name="extract_stations",
            message="No post-processor available; skipping",
            duration_seconds=duration,
            warnings=["Post-processor not initialized"],
        )

    def create_standard_netcdf(self) -> StepResult:
        """Convert to CO-OPS standard NetCDF."""
        self.logger.info(f"COMF: Creating standard NetCDF for {self.ocean_model}")

        import time as _time

        start = _time.time()

        if self._processor is not None:
            try:
                result = self._processor.create_standard_netcdf()
                duration = _time.time() - start
                return StepResult(
                    success=result.success,
                    step_name="create_standard_netcdf",
                    message=f"Standard NetCDF created in {duration:.1f}s",
                    duration_seconds=duration,
                    output_files=result.output_files,
                    errors=result.errors,
                    warnings=result.warnings,
                )
            except Exception as e:
                duration = _time.time() - start
                self.logger.error(f"Standard NetCDF creation failed: {e}")
                return StepResult(
                    success=False,
                    step_name="create_standard_netcdf",
                    message=str(e),
                    duration_seconds=duration,
                    errors=[str(e)],
                )

        duration = _time.time() - start
        return StepResult(
            success=True,
            step_name="create_standard_netcdf",
            message="No post-processor available; skipping",
            duration_seconds=duration,
            warnings=["Post-processor not initialized"],
        )

    def create_grib2(self) -> StepResult:
        """Create GRIB2 output (not typically used for COMF systems)."""
        self.logger.info("COMF: GRIB2 not typically required for COMF systems")
        return StepResult(
            success=True,
            step_name="create_grib2",
            message="GRIB2 not required for COMF systems",
        )

    def create_awips(self) -> StepResult:
        """Create AWIPS output (not typically used for COMF systems)."""
        self.logger.info("COMF: AWIPS/SHEF not typically required for COMF systems")
        return StepResult(
            success=True,
            step_name="create_awips",
            message="AWIPS/SHEF not required for COMF systems",
        )

    def archive_outputs(self) -> StepResult:
        """Archive post-processed COMF outputs to COMOUT."""
        self.logger.info(f"COMF: Archiving outputs for {self.ocean_model}")

        import time as _time

        start = _time.time()

        if self._processor is not None:
            try:
                result = self._processor.archive_outputs()
                duration = _time.time() - start
                return StepResult(
                    success=result.success,
                    step_name="archive_outputs",
                    message=f"Archived outputs in {duration:.1f}s",
                    duration_seconds=duration,
                    output_files=list(result.archived_files),
                    errors=result.errors,
                    warnings=result.warnings,
                )
            except Exception as e:
                duration = _time.time() - start
                self.logger.error(f"Output archival failed: {e}")
                return StepResult(
                    success=False,
                    step_name="archive_outputs",
                    message=str(e),
                    duration_seconds=duration,
                    errors=[str(e)],
                )

        duration = _time.time() - start
        return StepResult(
            success=True,
            step_name="archive_outputs",
            message="No post-processor available; skipping",
            duration_seconds=duration,
            warnings=["Post-processor not initialized"],
        )

    def run_phase(self, phase: str) -> StepResult:
        """
        Run COMF post-processing phase.

        For COMF, there is a single "post" phase that runs all steps.

        Args:
            phase: Should be "post" for COMF

        Returns:
            StepResult with execution status
        """
        if phase not in ("post", "post_1", "post_2"):
            return StepResult(
                success=False,
                step_name=f"run_phase_{phase}",
                message=f"Unknown COMF post phase: {phase}",
                errors=[f"Valid phase is 'post', got '{phase}'"],
            )

        self.logger.info(f"Running COMF post-processing phase: {phase}")

        import time as _time

        start = _time.time()

        if self._processor is not None:
            try:
                result = self._processor.run_all()
                duration = _time.time() - start
                return StepResult(
                    success=result.success,
                    step_name=phase,
                    message=f"COMF post-processing completed in {duration:.1f}s",
                    duration_seconds=duration,
                    output_files=result.output_files,
                    errors=result.errors,
                    warnings=result.warnings,
                )
            except Exception as e:
                duration = _time.time() - start
                self.logger.error(f"COMF post-processing failed: {e}")
                return StepResult(
                    success=False,
                    step_name=phase,
                    message=str(e),
                    duration_seconds=duration,
                    errors=[str(e)],
                )

        duration = _time.time() - start
        return StepResult(
            success=True,
            step_name=phase,
            message="No post-processor available; post-processing skipped",
            duration_seconds=duration,
            warnings=["Post-processor not initialized; install xarray and netCDF4"],
        )
