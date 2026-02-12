"""
STOFS Framework Handlers

Implements prep and model run orchestration for STOFS-3D Atlantic/Pacific
systems by calling existing STOFS shell scripts via subprocess.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BasePrepHandler, BaseModelRunHandler, StepResult

log = logging.getLogger(__name__)


class STOFSPrepHandler(BasePrepHandler):
    """
    STOFS-specific prep handler.

    Orchestrates STOFS preparation by calling existing shell scripts:
    - stofs_3d_atl_create_param_nml.sh
    - stofs_3d_atl_create_bctides_in.sh
    - stofs_3d_atl_create_surface_forcing_gfs.sh
    - stofs_3d_atl_create_surface_forcing_hrrr.sh
    - stofs_3d_atl_create_river_forcing_nwm.sh
    - stofs_3d_atl_create_river_st_lawrence.sh
    - stofs_3d_atl_create_obc_3d_th.sh
    - stofs_3d_atl_create_obc_nudge.sh
    """

    def __init__(self, config: Any):
        """
        Initialize STOFS prep handler.

        Args:
            config: OFSConfig instance with STOFS configuration
        """
        super().__init__(config)
        # Use environment variables as fallback since config might not have all attributes
        self.ush_dir = Path(
            os.environ.get(
                "USHstofs3d", os.environ.get("USHnos", getattr(config.runtime, "ush_ofs", "/tmp"))
            )
        )
        self.fix_dir = Path(
            os.environ.get(
                "FIXstofs3d", os.environ.get("FIXofs", getattr(config.runtime, "fix_ofs", "/tmp"))
            )
        )
        self.data_dir = Path(os.environ.get("DATA", getattr(config.runtime, "data", "/tmp")))

    def stage_static_files(self) -> StepResult:
        """
        Stage STOFS static files from fix/ directory.

        This is replicated from nos_ofs_prep_run.sh:_stofs_stage_static_files()
        """
        self.logger.info("Staging STOFS static files")

        try:
            os.chdir(self.data_dir)

            run = getattr(self.config, "RUN", "stofs_3d_atl")

            # Define static file mappings (source → target)
            static_files = {
                f"{run}_windrot_geo2proj.gr3": "windrot_geo2proj.gr3",
                f"{run}_watertype.gr3": "watertype.gr3",
                f"{run}_vgrid.in": "vgrid.in",
                f"{run}_tvd.prop": "tvd.prop",
                f"{run}_tem_nudge.gr3": "TEM_nudge.gr3",
                f"{run}_station.in": "station.in",
                f"{run}_river_source_sink.in": "source_sink.in",
                f"{run}_shapiro.gr3": "shapiro.gr3",
                f"{run}_sal_nudge.gr3": "SAL_nudge.gr3",
                f"{run}_param.nml_6globaloutput": "param.nml_template",
                f"{run}_river_msource.th": "msource.th",
                f"{run}_hgrid.ll": "hgrid.ll",
                f"{run}_hgrid.gr3": "hgrid.gr3",
                f"{run}_estuary.gr3": "estuary.gr3",
                f"{run}_drag.gr3": "drag.gr3",
                f"{run}_diffmin.gr3": "diffmin.gr3",
                f"{run}_diffmax.gr3": "diffmax.gr3",
                f"{run}_bctides.in_template": "bctides.in_template",
                f"{run}_albedo.gr3": "albedo.gr3",
                f"{run}_partition.prop": "partition.prop",
            }

            linked_files = []
            missing_files = []

            for src_name, dst_name in static_files.items():
                src = self.fix_dir / src_name
                dst = self.data_dir / dst_name

                if src.exists():
                    # Remove existing symlink/file
                    if dst.exists() or dst.is_symlink():
                        dst.unlink()
                    # Create symlink
                    dst.symlink_to(src)
                    linked_files.append(dst_name)
                else:
                    missing_files.append(src_name)

            if missing_files:
                self.logger.warning(
                    f"Some static files not found: {', '.join(missing_files[:5])}"
                )

            self.logger.info(f"Staged {len(linked_files)} STOFS static files")

            return StepResult(
                success=True,
                step_name="stage_static_files",
                message=f"Staged {len(linked_files)} files",
                output_files=[self.data_dir / f for f in linked_files],
                warnings=[f"Missing: {f}" for f in missing_files] if missing_files else [],
            )

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
        Create STOFS model configuration (param.nml, bctides.in).

        Calls:
        - stofs_3d_atl_create_param_nml.sh nowcast
        - stofs_3d_atl_create_param_nml.sh forecast
        - stofs_3d_atl_create_bctides_in.sh
        """
        self.logger.info("Creating STOFS model configuration")

        cycle = getattr(self.config, "cycle", "t00z")

        # Create param.nml for nowcast and forecast
        for phase in ["nowcast", "forecast"]:
            script = self.ush_dir / "stofs_3d_atl_create_param_nml.sh"
            command = f"{script} {phase}"
            result = self._run_subprocess(
                command,
                step_name=f"create_param_nml_{phase}",
                fatal=False,
            )
            if not result.success:
                return result

        # Create bctides.in
        script = self.ush_dir / "stofs_3d_atl_create_bctides_in.sh"
        result = self._run_subprocess(
            script,
            step_name="create_bctides_in",
            fatal=True,
        )

        return result

    def create_forcing_atmospheric(self) -> StepResult:
        """
        Create atmospheric forcing (GFS + HRRR).

        Calls:
        - stofs_3d_atl_create_surface_forcing_gfs.sh
        - stofs_3d_atl_create_surface_forcing_hrrr.sh
        """
        self.logger.info("Creating STOFS atmospheric forcing")

        # GFS forcing
        script = self.ush_dir / "stofs_3d_atl_create_surface_forcing_gfs.sh"
        result = self._run_subprocess(
            script,
            step_name="create_forcing_gfs",
            fatal=True,
        )
        if not result.success:
            return result

        # HRRR forcing
        script = self.ush_dir / "stofs_3d_atl_create_surface_forcing_hrrr.sh"
        result = self._run_subprocess(
            script,
            step_name="create_forcing_hrrr",
            fatal=True,
        )

        return result

    def create_forcing_river(self) -> StepResult:
        """
        Create river forcing (NWM + St. Lawrence).

        Calls:
        - stofs_3d_atl_create_river_forcing_nwm.sh
        - stofs_3d_atl_create_river_st_lawrence.sh
        """
        self.logger.info("Creating STOFS river forcing")

        # NWM forcing
        script = self.ush_dir / "stofs_3d_atl_create_river_forcing_nwm.sh"
        result = self._run_subprocess(
            script,
            step_name="create_forcing_nwm",
            fatal=True,
        )
        if not result.success:
            return result

        # St. Lawrence River forcing
        script = self.ush_dir / "stofs_3d_atl_create_river_st_lawrence.sh"
        result = self._run_subprocess(
            script,
            step_name="create_forcing_st_lawrence",
            fatal=True,
        )

        return result

    def create_forcing_obc(self) -> StepResult:
        """
        Create ocean boundary conditions (RTOFS 3D).

        Calls:
        - stofs_3d_atl_create_obc_3d_th.sh
        """
        self.logger.info("Creating STOFS OBC forcing")

        script = self.ush_dir / "stofs_3d_atl_create_obc_3d_th.sh"
        result = self._run_subprocess(
            script,
            step_name="create_obc_3d",
            fatal=True,
        )

        return result

    def create_forcing_nudging(self) -> StepResult:
        """
        Create interior nudging fields (RTOFS).

        Calls:
        - stofs_3d_atl_create_obc_nudge.sh

        Note: This is fatal in the shell version (uses err_chk).
        """
        self.logger.info("Creating STOFS nudging forcing")

        script = self.ush_dir / "stofs_3d_atl_create_obc_nudge.sh"
        result = self._run_subprocess(
            script,
            step_name="create_nudging",
            fatal=True,  # Fatal - matches shell err_chk
        )

        return result

    def prepare_initial_condition(self) -> StepResult:
        """
        Prepare restart/hotstart file for nowcast.

        Replicates logic from nos_ofs_prep_run.sh:_stofs_prepare_initial_condition()

        Searches for previous cycle hotstart or uses coldstart file.
        """
        self.logger.info("Preparing STOFS initial condition")

        try:
            coldstart = os.environ.get("COLDSTART", "NO")
            run = os.environ.get("RUN", "stofs_3d_atl")
            cycle = os.environ.get("cycle", "t00z")
            comout_rerun = Path(os.environ.get("COMOUTrerun", os.environ.get("COMOUT", "/tmp")))
            comin_stofs = Path(os.environ.get("COMINstofs", os.environ.get("COMIN", "/tmp")))

            fn_restart_rerun = comout_rerun / f"{run}.{cycle}.restart.nc"
            fn_restart_coldstart_fix = self.fix_dir / "stofs_3d_atl_restart_coldstart.nc"

            comout_rerun.mkdir(parents=True, exist_ok=True)

            # Create DATA_prep_restart subdirectory
            data_prep_restart = self.data_dir / "DATA_prep_restart"
            data_prep_restart.mkdir(parents=True, exist_ok=True)

            if coldstart == "YES":
                self.logger.info("COLDSTART=YES, using coldstart file from fix/")
                # Check file exists and is >20GB
                if (
                    fn_restart_coldstart_fix.exists()
                    and fn_restart_coldstart_fix.stat().st_size > 20 * 1024**3
                ):
                    import shutil

                    shutil.copy2(fn_restart_coldstart_fix, fn_restart_rerun)
                    self.logger.info(f"Copied coldstart to {fn_restart_rerun}")
                else:
                    return StepResult(
                        success=False,
                        step_name="prepare_initial_condition",
                        message="Coldstart file not found or too small (<20GB)",
                        errors=[
                            f"Not found or invalid: {fn_restart_coldstart_fix} "
                            f"(size: {fn_restart_coldstart_fix.stat().st_size if fn_restart_coldstart_fix.exists() else 0} bytes)"
                        ],
                    )
            else:
                # Search for previous cycle hotstart
                self.logger.info("Searching for previous cycle hotstart")

                import datetime

                pdy = getattr(self.config, "PDY", datetime.datetime.now().strftime("%Y%m%d"))
                pdyhh_ncast_begin = getattr(self.config, "PDYHH_NCAST_BEGIN", f"{pdy}00")

                found = False
                for days_back in range(5):
                    try:
                        base_date = datetime.datetime.strptime(pdyhh_ncast_begin[:8], "%Y%m%d")
                        search_date = base_date - datetime.timedelta(days=days_back)
                        date_str = search_date.strftime("%Y%m%d")

                        fn_hotstart = comin_stofs / f"{run}.{date_str}" / f"{run}.{cycle}.hotstart.stofs3d.nc"

                        if fn_hotstart.exists() and fn_hotstart.stat().st_size > 20 * 1024**3:
                            self.logger.info(f"Found hotstart: {fn_hotstart}")
                            import shutil

                            shutil.copy2(fn_hotstart, fn_restart_rerun)
                            found = True
                            break
                        else:
                            self.logger.debug(f"Not found or too small: {fn_hotstart}")
                    except Exception as e:
                        self.logger.warning(f"Error checking {days_back} days back: {e}")
                        continue

                if not found:
                    self.logger.warning("No previous hotstart found")
                    return StepResult(
                        success=False,
                        step_name="prepare_initial_condition",
                        message="No previous hotstart found",
                        errors=["No valid hotstart file found in previous 5 days"],
                    )

            return StepResult(
                success=True,
                step_name="prepare_initial_condition",
                message=f"Restart prepared: {fn_restart_rerun}",
                output_files=[fn_restart_rerun],
            )

        except Exception as e:
            self.logger.exception(f"Failed to prepare initial condition: {e}")
            return StepResult(
                success=False,
                step_name="prepare_initial_condition",
                message=str(e),
                errors=[str(e)],
            )


class STOFSModelRunHandler(BaseModelRunHandler):
    """
    STOFS-specific model run handler.

    Orchestrates STOFS model execution for nowcast/forecast phases.
    """

    def __init__(self, config: Any):
        """
        Initialize STOFS model run handler.

        Args:
            config: OFSConfig instance with STOFS configuration
        """
        super().__init__(config)
        # Use environment variables as fallback
        self.ush_dir = Path(
            os.environ.get(
                "USHstofs3d", os.environ.get("USHnos", getattr(config.runtime, "ush_ofs", "/tmp"))
            )
        )
        self.fix_dir = Path(
            os.environ.get(
                "FIXstofs3d", os.environ.get("FIXofs", getattr(config.runtime, "fix_ofs", "/tmp"))
            )
        )
        self.exec_dir = Path(
            os.environ.get(
                "EXECstofs3d",
                os.environ.get("EXECnos", getattr(config.runtime, "exec_ofs", "/tmp")),
            )
        )
        self.data_dir = Path(os.environ.get("DATA", getattr(config.runtime, "data", "/tmp")))
        self.comout = Path(os.environ.get("COMOUT", getattr(config.runtime, "comout", "/tmp")))
        self.comout_rerun = Path(
            os.environ.get("COMOUTrerun", os.environ.get("COMOUT", "/tmp"))
        )

    def stage_model_files(self, phase: str) -> StepResult:
        """
        Stage forcing and static files for model run.

        Replicates logic from nos_ofs_model_run.sh:_stofs_stage_files()
        """
        self.logger.info(f"Staging STOFS files for {phase}")

        # This is a Python implementation of the shell logic
        # For simplicity, we call the shell function
        ush_script = Path(os.getenv("USHnos", self.ush_dir.parent))
        command = f"source {ush_script}/nos_ofs_model_run.sh && stage_model_files {phase}"

        result = self._run_subprocess(
            command,
            step_name=f"stage_files_{phase}",
            fatal=True,
            timeout=600,
        )

        return result

    def prepare_restart(self, phase: str) -> StepResult:
        """
        Prepare hotstart file for nowcast or forecast.

        Replicates logic from nos_ofs_model_run.sh:_stofs_prepare_restart()
        """
        self.logger.info(f"Preparing STOFS restart for {phase}")

        ush_script = Path(os.getenv("USHnos", self.ush_dir.parent))
        command = f"source {ush_script}/nos_ofs_model_run.sh && prepare_restart {phase}"

        result = self._run_subprocess(
            command,
            step_name=f"prepare_restart_{phase}",
            fatal=True,
            timeout=1800,
        )

        return result

    def execute_model(self, phase: str) -> StepResult:
        """
        Execute SCHISM for nowcast or forecast.

        Replicates logic from nos_ofs_model_run.sh:_stofs_execute_model()
        """
        self.logger.info(f"Executing STOFS {phase}")

        ush_script = Path(os.getenv("USHnos", self.ush_dir.parent))
        command = f"source {ush_script}/nos_ofs_model_run.sh && execute_model {phase}"

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
        Archive STOFS outputs to COMOUT.

        Replicates logic from nos_ofs_model_run.sh:_stofs_archive_outputs()
        """
        self.logger.info(f"Archiving STOFS outputs for {phase}")

        ush_script = Path(os.getenv("USHnos", self.ush_dir.parent))
        command = f"source {ush_script}/nos_ofs_model_run.sh && archive_outputs {phase}"

        result = self._run_subprocess(
            command,
            step_name=f"archive_outputs_{phase}",
            fatal=True,
            timeout=1800,
        )

        return result
