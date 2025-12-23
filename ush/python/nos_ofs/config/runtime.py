"""
Runtime Configuration - From environment variables

RuntimeConfig captures "where/when are we running?" from the NCO
environment. This is mutable and changes each run, unlike SystemConfig.

Standard NCO environment variables:
- PDY: Production date (YYYYMMDD)
- cyc: Cycle hour (00, 06, 12, 18)
- HOMEnos: Package installation directory
- FIXofs: Static input files directory
- DATA: Working directory
- COMOUT: Output directory
- COMINgfs, COMINhrrr, etc.: Input data paths
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .system import SystemConfig
    from .validation import ValidationResult


@dataclass
class RuntimeConfig:
    """
    Runtime configuration from environment variables.

    This is MUTABLE - represents the current execution context.
    Populated from NCO environment variables set by ecflow/job control.

    Attributes:
        pdy: Production date YYYYMMDD
        cyc: Cycle hour (0, 6, 12, 18)
        envir: Environment (prod, para, dev)
        run: Run name (usually same as system name)
        net: Network name
        home_nos: Package installation directory (HOMEnos)
        fix_ofs: Static input files directory (FIXofs)
        exec_ofs: Executables directory (EXECofs)
        parm_ofs: Parameter files directory (PARMofs)
        ush_ofs: Utility scripts directory (USHofs)
        data: Working directory (DATA)
        comout: Output directory (COMOUT)
        comout_rerun: Rerun output directory (COMOUTrerun)
        comin_*: Input data paths for various sources
    """

    # Cycle information
    pdy: str = ""
    cyc: int = 12
    envir: str = "dev"

    # System identity
    run: str = ""
    net: str = ""

    # Installation paths
    home_nos: Optional[Path] = None
    fix_ofs: Optional[Path] = None
    exec_ofs: Optional[Path] = None
    parm_ofs: Optional[Path] = None
    ush_ofs: Optional[Path] = None

    # Working/output paths
    data: Optional[Path] = None
    comout: Optional[Path] = None
    comout_rerun: Optional[Path] = None
    comin: Optional[Path] = None

    # Input data paths
    comin_gfs: Optional[Path] = None
    comin_hrrr: Optional[Path] = None
    comin_nam: Optional[Path] = None
    comin_rtofs: Optional[Path] = None
    comin_nwm: Optional[Path] = None
    comin_adt: Optional[Path] = None
    dcom_root: Optional[Path] = None

    # Control flags
    keepdata: bool = False
    sendcom: bool = True
    senddbn: bool = True

    # Store all environment variables for reference
    _env: Dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_environment(cls) -> "RuntimeConfig":
        """
        Build RuntimeConfig from environment variables.

        Reads standard NCO environment variables and maps them to
        config attributes. Supports both COMF (HOMEnos) and STOFS
        (HOMEstofs) naming conventions.

        Returns:
            RuntimeConfig instance
        """
        env = dict(os.environ)

        def get_path(var: str, *alt_vars: str) -> Optional[Path]:
            """Get path from env var, checking alternatives."""
            for v in (var,) + alt_vars:
                val = env.get(v)
                if val:
                    return Path(val)
            return None

        def get_str(var: str, *alt_vars: str, default: str = "") -> str:
            """Get string from env var, checking alternatives."""
            for v in (var,) + alt_vars:
                val = env.get(v)
                if val:
                    return val
            return default

        def get_bool(var: str, default: bool = False) -> bool:
            """Get boolean from env var."""
            val = env.get(var, "").upper()
            if val in ("YES", "TRUE", "1"):
                return True
            if val in ("NO", "FALSE", "0"):
                return False
            return default

        # Get PDY with fallback to today
        pdy = get_str("PDY")
        if not pdy:
            pdy = datetime.now().strftime("%Y%m%d")

        return cls(
            # Cycle info
            pdy=pdy,
            cyc=int(get_str("cyc", default="12")),
            envir=get_str("envir", default="dev"),
            # System identity
            run=get_str("RUN"),
            net=get_str("NET"),
            # Installation paths - support both COMF and STOFS naming
            home_nos=get_path("HOMEnos", "HOMEstofs"),
            fix_ofs=get_path("FIXofs", "FIXstofs3d"),
            exec_ofs=get_path("EXECofs", "EXECstofs3d"),
            parm_ofs=get_path("PARMofs", "PARMstofs"),
            ush_ofs=get_path("USHofs", "USHstofs3d"),
            # Working/output paths
            data=get_path("DATA"),
            comout=get_path("COMOUT"),
            comout_rerun=get_path("COMOUTrerun"),
            comin=get_path("COMIN"),
            # Input data paths
            comin_gfs=get_path("COMINgfs"),
            comin_hrrr=get_path("COMINhrrr"),
            comin_nam=get_path("COMINnam"),
            comin_rtofs=get_path("COMINrtofs"),
            comin_nwm=get_path("COMINnwm"),
            comin_adt=get_path("COMINadt"),
            dcom_root=get_path("DCOMROOT"),
            # Control flags
            keepdata=get_bool("KEEPDATA", False),
            sendcom=get_bool("SENDCOM", True),
            senddbn=get_bool("SENDDBN", True),
            # Store full env for reference
            _env=env,
        )

    @property
    def cycle_str(self) -> str:
        """
        Return cycle string in NCO format.

        Returns:
            Cycle string like 't12z'
        """
        return f"t{self.cyc:02d}z"

    @property
    def cycle_datetime(self) -> datetime:
        """
        Return cycle as datetime object.

        Returns:
            datetime for the cycle
        """
        return datetime.strptime(f"{self.pdy}{self.cyc:02d}", "%Y%m%d%H")

    @property
    def pdy_date(self) -> datetime:
        """
        Return PDY as date object.

        Returns:
            datetime for PDY (midnight)
        """
        return datetime.strptime(self.pdy, "%Y%m%d")

    def get_env(self, var: str, default: str = "") -> str:
        """
        Get an environment variable value.

        Args:
            var: Environment variable name
            default: Default value if not set

        Returns:
            Variable value or default
        """
        return self._env.get(var, default)

    def validate(self, system: "SystemConfig") -> "ValidationResult":
        """
        Validate runtime config against system requirements.

        Checks that required paths exist and forcing input paths
        are available for enabled forcing types.

        Args:
            system: SystemConfig to validate against

        Returns:
            ValidationResult with errors and warnings
        """
        from .validation import RuntimeValidator

        return RuntimeValidator(self, system).validate()

    def ensure_directories(self) -> None:
        """
        Create working and output directories if they don't exist.

        Creates DATA, COMOUT, and COMOUTrerun directories.
        """
        for path in [self.data, self.comout, self.comout_rerun]:
            if path is not None:
                path.mkdir(parents=True, exist_ok=True)

    def get_forcing_path(self, source: str) -> Optional[Path]:
        """
        Get input path for a forcing source.

        Args:
            source: Forcing source name (gfs, hrrr, nam, rtofs, nwm, adt)

        Returns:
            Path to forcing input directory or None
        """
        path_map = {
            "gfs": self.comin_gfs,
            "hrrr": self.comin_hrrr,
            "nam": self.comin_nam,
            "rtofs": self.comin_rtofs,
            "nwm": self.comin_nwm,
            "adt": self.comin_adt,
        }
        return path_map.get(source.lower())

    def to_env_dict(self) -> Dict[str, str]:
        """
        Convert runtime config back to environment variable dict.

        Useful for passing to subprocess calls.

        Returns:
            Dictionary of environment variables
        """
        env = {}

        if self.pdy:
            env["PDY"] = self.pdy
        env["cyc"] = str(self.cyc)
        if self.envir:
            env["envir"] = self.envir
        if self.run:
            env["RUN"] = self.run
        if self.net:
            env["NET"] = self.net

        if self.home_nos:
            env["HOMEnos"] = str(self.home_nos)
        if self.fix_ofs:
            env["FIXofs"] = str(self.fix_ofs)
        if self.exec_ofs:
            env["EXECofs"] = str(self.exec_ofs)
        if self.data:
            env["DATA"] = str(self.data)
        if self.comout:
            env["COMOUT"] = str(self.comout)

        if self.comin_gfs:
            env["COMINgfs"] = str(self.comin_gfs)
        if self.comin_hrrr:
            env["COMINhrrr"] = str(self.comin_hrrr)
        if self.comin_rtofs:
            env["COMINrtofs"] = str(self.comin_rtofs)
        if self.comin_nwm:
            env["COMINnwm"] = str(self.comin_nwm)

        env["KEEPDATA"] = "YES" if self.keepdata else "NO"
        env["SENDCOM"] = "YES" if self.sendcom else "NO"
        env["SENDDBN"] = "YES" if self.senddbn else "NO"

        return env

    def __repr__(self) -> str:
        return (
            f"RuntimeConfig(pdy={self.pdy}, cyc={self.cyc}, "
            f"envir={self.envir}, run={self.run})"
        )
