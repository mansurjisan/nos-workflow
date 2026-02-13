"""
Ensemble Member Management

Manages the lifecycle of ensemble members including:
- Directory creation for each member
- Configuration cloning and modification
- Perturbation application
- Status tracking

Each ensemble member is a full model run with its own working directory,
perturbed configuration, and independent checkpoint/restart capability.
The MemberManager coordinates creation and perturbation of all members.
"""

import copy
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import (
    EnsembleConfig,
    ICPerturbationConfig,
    ForcingPerturbationConfig,
    OBCPerturbationConfig,
    ParamPerturbationConfig,
)
from .perturbation import (
    BasePerturbation,
    PerturbationResult,
    GaussianICPerturbation,
    EOFPerturbation,
    HistoricalPerturbation,
    WindPerturbation,
    PressurePerturbation,
    PrecipPerturbation,
    OBCPerturbation,
    BottomFrictionPerturbation,
    WindDragPerturbation,
    MixingPerturbation,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ensemble member dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnsembleMember:
    """
    Represents a single ensemble member.

    Each member has its own working directory, a copy of the model
    configuration (potentially with perturbed parameters), and a record
    of all perturbations applied.

    Attributes:
        member_id: Ensemble member index (0-based).
        data_dir: Working directory for this member's model run.
        base_config: Reference to the unmodified OFSConfig (shared, not copied).
        perturbations: List of PerturbationResult records describing
                       all perturbations applied to this member.
        status: Current status string.
        result: Model run result once execution completes.
        parameter_overrides: Dictionary of parameter names to perturbed values
                             (aggregated from all parameter perturbations).
        metadata: Arbitrary metadata dictionary.
    """

    member_id: int
    data_dir: Path
    base_config: Any  # OFSConfig (avoid circular import)
    perturbations: List[PerturbationResult] = field(default_factory=list)
    status: str = "pending"
    result: Optional[Any] = None  # ModelRunResult
    parameter_overrides: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def member_name(self) -> str:
        """Formatted member name (e.g., 'member_0003')."""
        return f"member_{self.member_id:04d}"

    @property
    def is_completed(self) -> bool:
        """Check if member run has completed (successfully or not)."""
        return self.status in ("completed", "failed")

    @property
    def is_successful(self) -> bool:
        """Check if member completed successfully."""
        return self.status == "completed"

    @property
    def all_perturbations_successful(self) -> bool:
        """Check if all perturbations were applied successfully."""
        return all(p.success for p in self.perturbations)

    def summary(self) -> str:
        """Return a human-readable summary of this member."""
        lines = [
            f"Member {self.member_id:04d} [{self.status}]",
            f"  Directory: {self.data_dir}",
            f"  Perturbations: {len(self.perturbations)}",
        ]
        for p in self.perturbations:
            status = "OK" if p.success else "FAIL"
            lines.append(f"    [{status}] {p.perturbation_type}: {p.description}")
        if self.parameter_overrides:
            lines.append(f"  Parameter overrides: {self.parameter_overrides}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Member manager
# ---------------------------------------------------------------------------


class MemberManager:
    """
    Creates and manages ensemble members.

    Responsibilities:
    - Create N member working directories under the ensemble output root.
    - Clone base forcing/config files into each member directory.
    - Instantiate and apply the configured perturbation strategies.
    - Track member status.

    The manager creates reproducible perturbations by deriving a unique
    random seed for each member from the base seed: seed_i = base_seed + i.
    This ensures that adding members does not change the perturbations
    of existing members.

    Attributes:
        base_config: The unmodified OFSConfig.
        ensemble_config: EnsembleConfig with perturbation settings.
        members: List of created EnsembleMember instances.
    """

    def __init__(self, base_config: Any, ensemble_config: EnsembleConfig):
        """
        Initialize member manager.

        Args:
            base_config: OFSConfig instance (unmodified baseline).
            ensemble_config: EnsembleConfig with ensemble settings.
        """
        self.base_config = base_config
        self.ensemble_config = ensemble_config
        self.members: List[EnsembleMember] = []

        self._output_dir = ensemble_config.output_dir
        self._base_seed = ensemble_config.perturbation_seed

    def create_members(
        self,
        base_data_dir: Optional[Path] = None,
        link_shared: bool = True,
    ) -> List[EnsembleMember]:
        """
        Create ensemble member directories and apply perturbations.

        For each member:
        1. Create member_NNNN directory under output_dir.
        2. Copy/link base forcing and static files.
        3. Apply configured perturbations.

        Args:
            base_data_dir: Path to the base (deterministic) working
                           directory containing forcing files to clone.
                           If None, uses config.runtime.data or output_dir/base.
            link_shared: If True, use symlinks for large unperturbed files
                         (saves disk space). If False, copy all files.

        Returns:
            List of EnsembleMember instances.
        """
        n_members = self.ensemble_config.n_members
        log.info(
            f"Creating {n_members} ensemble members under {self._output_dir}"
        )

        # Determine base data directory
        if base_data_dir is None:
            runtime_data = getattr(self.base_config, "runtime", None)
            if runtime_data and hasattr(runtime_data, "data") and runtime_data.data:
                base_data_dir = Path(runtime_data.data)
            else:
                base_data_dir = self._output_dir / "base"

        self.members = []

        for i in range(n_members):
            member_dir = self._output_dir / f"member_{i:04d}"
            member_dir.mkdir(parents=True, exist_ok=True)

            # Clone base data into member directory
            if base_data_dir.exists():
                self._clone_data(base_data_dir, member_dir, link_shared)

            member = EnsembleMember(
                member_id=i,
                data_dir=member_dir,
                base_config=self.base_config,
            )

            # Apply perturbations
            self._apply_perturbations(member)

            self.members.append(member)
            log.info(
                f"  Member {i:04d}: "
                f"{len(member.perturbations)} perturbations, "
                f"all_ok={member.all_perturbations_successful}"
            )

        return self.members

    def get_member(self, member_id: int) -> Optional[EnsembleMember]:
        """
        Get a member by ID.

        Args:
            member_id: Member index.

        Returns:
            EnsembleMember or None if not found.
        """
        for m in self.members:
            if m.member_id == member_id:
                return m
        return None

    def get_pending_members(self) -> List[EnsembleMember]:
        """Return members that have not yet been run."""
        return [m for m in self.members if m.status == "pending"]

    def get_completed_members(self) -> List[EnsembleMember]:
        """Return members that have completed (success or failure)."""
        return [m for m in self.members if m.is_completed]

    def get_successful_members(self) -> List[EnsembleMember]:
        """Return members that completed successfully."""
        return [m for m in self.members if m.is_successful]

    def get_failed_members(self) -> List[EnsembleMember]:
        """Return members that failed."""
        return [m for m in self.members if m.status == "failed"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clone_data(
        self, src_dir: Path, dst_dir: Path, link_shared: bool
    ) -> None:
        """
        Clone base data into a member directory.

        If link_shared is True, creates symlinks to large files and copies
        only small files that will be modified by perturbations.

        Args:
            src_dir: Source (base) data directory.
            dst_dir: Destination member directory.
            link_shared: Whether to symlink rather than copy large files.
        """
        # Files that perturbations will modify (must be copies, not links)
        mutable_patterns = {
            "*.nml",
            "param.nml",
            "hotstart*.nc",
            "*restart*.nc",
            "sflux_air_*.nc",
            "sflux_prc_*.nc",
            "sflux_rad_*.nc",
            "*_3D.th.nc",
            "elev2D.th.nc",
            "uv3D.th.nc",
            "*.in",
            "ROMS.in",
        }

        if not src_dir.exists():
            return

        for src_item in src_dir.iterdir():
            dst_item = dst_dir / src_item.name

            if dst_item.exists():
                continue

            if src_item.is_dir():
                # Recursively clone subdirectories (e.g., sflux/)
                dst_item.mkdir(exist_ok=True)
                self._clone_data(src_item, dst_item, link_shared)
            else:
                # Decide: copy or link
                is_mutable = any(
                    src_item.match(p) for p in mutable_patterns
                )

                if is_mutable or not link_shared:
                    shutil.copy2(str(src_item), str(dst_item))
                else:
                    try:
                        dst_item.symlink_to(src_item.resolve())
                    except OSError:
                        # Fall back to copy if symlink fails
                        shutil.copy2(str(src_item), str(dst_item))

    def _apply_perturbations(self, member: EnsembleMember) -> None:
        """
        Apply all configured perturbations to a member.

        Creates a unique RNG for each member based on (base_seed + member_id)
        to ensure reproducibility and independence.

        Args:
            member: EnsembleMember to perturb.
        """
        member_seed = self._base_seed + member.member_id
        rng = np.random.default_rng(member_seed)

        ec = self.ensemble_config

        # 1. Initial condition perturbations
        if ec.ic_perturbation.enabled:
            ic_pert = self._create_ic_perturbation(ec.ic_perturbation, rng)
            if ic_pert is not None:
                result = ic_pert.apply(member.member_id, member.data_dir)
                member.perturbations.append(result)

        # 2. Atmospheric forcing perturbations
        if ec.forcing_perturbation.enabled:
            # Wind
            if ec.forcing_perturbation.wind.enabled:
                wind_pert = WindPerturbation(
                    ec.forcing_perturbation.wind, rng
                )
                result = wind_pert.apply(member.member_id, member.data_dir)
                member.perturbations.append(result)

            # Pressure
            if ec.forcing_perturbation.pressure.enabled:
                pres_pert = PressurePerturbation(
                    ec.forcing_perturbation.pressure, rng
                )
                result = pres_pert.apply(member.member_id, member.data_dir)
                member.perturbations.append(result)

            # Precipitation
            if ec.forcing_perturbation.precipitation.enabled:
                precip_pert = PrecipPerturbation(
                    ec.forcing_perturbation.precipitation, rng
                )
                result = precip_pert.apply(member.member_id, member.data_dir)
                member.perturbations.append(result)

        # 3. Boundary condition perturbations
        if ec.obc_perturbation.enabled:
            obc_pert = OBCPerturbation(ec.obc_perturbation, rng)
            result = obc_pert.apply(member.member_id, member.data_dir)
            member.perturbations.append(result)

        # 4. Model parameter perturbations
        if ec.param_perturbation.enabled:
            if ec.param_perturbation.bottom_friction_std_pct > 0:
                bf_pert = BottomFrictionPerturbation(
                    ec.param_perturbation, rng
                )
                result = bf_pert.apply(member.member_id, member.data_dir)
                member.perturbations.append(result)
                if result.parameters:
                    member.parameter_overrides.update(result.parameters)

            if ec.param_perturbation.wind_drag_std_pct > 0:
                wd_pert = WindDragPerturbation(ec.param_perturbation, rng)
                result = wd_pert.apply(member.member_id, member.data_dir)
                member.perturbations.append(result)
                if result.parameters:
                    member.parameter_overrides.update(result.parameters)

            if ec.param_perturbation.mixing_std_pct > 0:
                mx_pert = MixingPerturbation(ec.param_perturbation, rng)
                result = mx_pert.apply(member.member_id, member.data_dir)
                member.perturbations.append(result)
                if result.parameters:
                    member.parameter_overrides.update(result.parameters)

    @staticmethod
    def _create_ic_perturbation(
        config: ICPerturbationConfig, rng: np.random.Generator
    ) -> Optional[BasePerturbation]:
        """
        Create the appropriate IC perturbation based on config method.

        Args:
            config: IC perturbation configuration.
            rng: Random generator.

        Returns:
            BasePerturbation instance or None if method is unknown.
        """
        method = config.method.lower()

        if method == "gaussian":
            return GaussianICPerturbation(config, rng)
        elif method == "eof":
            return EOFPerturbation(config, rng)
        elif method == "historical":
            return HistoricalPerturbation(config, rng)
        else:
            log.warning(
                f"Unknown IC perturbation method: {method}. "
                f"Supported: gaussian, eof, historical"
            )
            return None
