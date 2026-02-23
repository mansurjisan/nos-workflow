"""
Ensemble Parameter Generator

Generates perturbed parameter sets for ensemble model runs using
Latin Hypercube Sampling (LHS). Member 000 is always the control
run with unperturbed default values.

Supports three ensemble methods:
  - parameter_perturbation: LHS-based physics parameter perturbation only
  - atmospheric:            Different atmospheric forcing sources per member
  - gefs:                   GEFS atmospheric ensemble + optional LHS physics
                            perturbation. Each member gets a distinct GEFS
                            perturbation member for atmospheric forcing.
                            Member 000 = GFS control + default physics.
                            Members 001+ = GEFS gep01..N + LHS-perturbed physics.

Supports two distribution types:
  - uniform:     Linear uniform sampling between [min, max]
  - log_uniform: Uniform sampling in log10 space (good for parameters
                 spanning orders of magnitude, e.g., mixing coefficients)

Supports two model types:
  - SCHISM:  Parameters applied to param.nml (Fortran namelist)
             Perturbable: rdrg2, zob, akt_bak, akv_bak, scale_hflux
  - ADCIRC:  Parameters applied to fort.15 (plain text, sed-based)
             Perturbable: ffactor (friction scaling), eslm (lateral viscosity),
                          tau0 (GWCE weighting factor)

Usage:
    # From Python
    config = EnsembleConfig.from_yaml("secofs.yaml")
    generator = ParamGenerator(config)
    members = generator.generate()  # List of dicts

    # From command line
    python -m nos_ofs.ensemble.param_generator secofs 5 --seed 42
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ParameterDef:
    """Definition of a single perturbable parameter."""
    name: str
    min_val: float
    max_val: float
    default: float
    distribution: str = "uniform"
    description: str = ""

    def validate(self):
        """Check that parameter bounds are physically reasonable."""
        if self.min_val >= self.max_val:
            raise ValueError(
                f"Parameter '{self.name}': min ({self.min_val}) "
                f"must be less than max ({self.max_val})"
            )
        if not (self.min_val <= self.default <= self.max_val):
            raise ValueError(
                f"Parameter '{self.name}': default ({self.default}) "
                f"must be between min ({self.min_val}) and max ({self.max_val})"
            )
        if self.distribution == "log_uniform" and self.min_val <= 0:
            raise ValueError(
                f"Parameter '{self.name}': log_uniform requires min > 0 "
                f"(got {self.min_val})"
            )
        if self.distribution not in ("uniform", "log_uniform"):
            raise ValueError(
                f"Parameter '{self.name}': unknown distribution "
                f"'{self.distribution}' (expected 'uniform' or 'log_uniform')"
            )


@dataclass
class AtmosphericMemberConfig:
    """Atmospheric forcing configuration for a single ensemble member."""
    label: str
    met_source_1: str                    # Primary met source (GFS, NAM, etc.)
    met_source_2: Optional[str] = None   # Secondary met source (HRRR, etc.)


@dataclass
class AtmosphericEnsembleConfig:
    """Configuration for atmospheric forcing ensemble."""
    enabled: bool = False
    members: Dict[str, AtmosphericMemberConfig] = field(default_factory=dict)
    extra_sources: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "AtmosphericEnsembleConfig":
        """Parse atmospheric_ensemble section from YAML dict."""
        if not data or not data.get("enabled", False):
            return cls(enabled=False)

        members = {}
        for mid, mdef in data.get("members", {}).items():
            mid_str = str(mid).zfill(3)
            members[mid_str] = AtmosphericMemberConfig(
                label=mdef.get("label", ""),
                met_source_1=mdef.get("met_source_1", "GFS"),
                met_source_2=mdef.get("met_source_2"),
            )

        return cls(
            enabled=True,
            members=members,
            extra_sources=data.get("extra_sources", []),
        )


@dataclass
class GEFSMemberConfig:
    """GEFS atmospheric forcing configuration for a single ensemble member."""
    label: str
    met_source_1: str                    # Primary met source (GFS, GEFS_01, etc.)
    met_source_2: Optional[str] = None   # Secondary met source (HRRR, etc.)


@dataclass
class GEFSEnsembleConfig:
    """Configuration for GEFS atmospheric forcing ensemble.

    GEFS provides 30 physically consistent perturbation members from
    perturbed initial conditions and stochastic physics. This replaces
    the 3-source atmospheric ensemble (GFS/HRRR/NAM switching) with
    statistically robust atmospheric uncertainty quantification.
    """
    enabled: bool = False
    n_gefs_members: int = 0
    resolution: str = "0p50"
    product: str = "pgrb2ap5"
    control_member: str = "gec00"
    perturbation_prefix: str = "gep"
    members: Dict[str, GEFSMemberConfig] = field(default_factory=dict)
    extra_sources: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "GEFSEnsembleConfig":
        """Parse gefs section from YAML dict."""
        if not data or not data.get("enabled", False):
            return cls(enabled=False)

        members = {}
        for mid, mdef in data.get("members", {}).items():
            mid_str = str(mid).zfill(3)
            members[mid_str] = GEFSMemberConfig(
                label=mdef.get("label", f"GEFS member {mid_str}"),
                met_source_1=mdef.get("met_source_1", "GFS"),
                met_source_2=mdef.get("met_source_2"),
            )

        return cls(
            enabled=True,
            n_gefs_members=int(data.get("n_gefs_members", len(members))),
            resolution=data.get("resolution", "0p50"),
            product=data.get("product", "pgrb2ap5"),
            control_member=data.get("control_member", "gec00"),
            perturbation_prefix=data.get("perturbation_prefix", "gep"),
            members=members,
            extra_sources=data.get("extra_sources", []),
        )


# Default parameter definitions for ADCIRC models.
# Used as reference when building YAML configs for ADCIRC ensemble runs.
# The actual parameter ranges come from the YAML ensemble.parameters section.
ADCIRC_PARAMS = {
    "ffactor": {
        "range": [0.8, 1.2],
        "default": 1.0,
        "distribution": "uniform",
        "description": "Friction factor scaling (multiplies CF in fort.15)",
    },
    "eslm": {
        "range": [10.0, 100.0],
        "default": 50.0,
        "distribution": "log_uniform",
        "description": "Lateral eddy viscosity / Smagorinsky coefficient",
    },
    "tau0": {
        "range": [-3.0, -1.0],
        "default": -3.0,
        "distribution": "uniform",
        "description": "GWCE weighting factor (negative = spatially variable)",
    },
}


@dataclass
class EnsembleConfig:
    """Configuration for an ensemble run.

    Supports both SCHISM (param.nml) and ADCIRC (fort.15) model types.
    The model_type field is read from the OFS YAML and determines how
    parameter perturbations are applied by the shell-side ensemble library.
    """
    n_members: int
    method: str
    seed: int
    model_type: str = "schism"
    perturb_physics: bool = True
    parameters: List[ParameterDef] = field(default_factory=list)
    atmospheric: AtmosphericEnsembleConfig = field(
        default_factory=AtmosphericEnsembleConfig
    )
    gefs: GEFSEnsembleConfig = field(
        default_factory=GEFSEnsembleConfig
    )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "EnsembleConfig":
        """Load ensemble config from an OFS YAML file.

        Args:
            yaml_path: Path to the OFS system YAML (e.g., secofs.yaml)

        Returns:
            EnsembleConfig instance
        """
        import yaml

        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        ens = data.get("ensemble")
        if not ens:
            raise ValueError(f"No 'ensemble' section found in {yaml_path}")

        if not ens.get("enabled", False):
            raise ValueError(
                f"Ensemble is not enabled in {yaml_path}. "
                "Set ensemble.enabled: true"
            )

        # Detect model type from system section
        system = data.get("system", {})
        model_type = system.get("model_type", "schism").lower()

        perturb_physics = ens.get("perturb_physics", True)

        params = []
        if perturb_physics:
            for name, pdef in ens.get("parameters", {}).items():
                params.append(ParameterDef(
                    name=name,
                    min_val=float(pdef["min"]),
                    max_val=float(pdef["max"]),
                    default=float(pdef.get("default", (pdef["min"] + pdef["max"]) / 2)),
                    distribution=pdef.get("distribution", "uniform"),
                    description=pdef.get("description", ""),
                ))

        atmospheric = AtmosphericEnsembleConfig.from_dict(
            ens.get("atmospheric_ensemble")
        )

        gefs = GEFSEnsembleConfig.from_dict(
            ens.get("gefs")
        )

        return cls(
            n_members=int(ens.get("n_members", 5)),
            method=ens.get("method", "parameter_perturbation"),
            seed=int(ens.get("seed", 42)),
            model_type=model_type,
            perturb_physics=perturb_physics,
            parameters=params,
            atmospheric=atmospheric,
            gefs=gefs,
        )

    def validate(self):
        """Validate the ensemble configuration."""
        if self.n_members < 2:
            raise ValueError(
                f"n_members must be >= 2 (got {self.n_members}). "
                "Need at least control + 1 perturbed member."
            )
        if self.method == "atmospheric":
            # Atmospheric-only mode: parameters are optional (all members
            # use defaults), but atmospheric ensemble must be enabled.
            if not self.atmospheric.enabled:
                raise ValueError(
                    "method: atmospheric requires "
                    "atmospheric_ensemble.enabled: true"
                )
        elif self.method == "gefs":
            # GEFS mode: gefs config must be enabled
            if not self.gefs.enabled:
                raise ValueError(
                    "method: gefs requires gefs.enabled: true"
                )
            # Verify that GEFS member definitions cover all ensemble members
            for i in range(self.n_members):
                mid = f"{i:03d}"
                if mid not in self.gefs.members:
                    raise ValueError(
                        f"method: gefs requires gefs.members to define "
                        f"member '{mid}', but it was not found. "
                        f"Defined members: {list(self.gefs.members.keys())}"
                    )
            # Parameters are optional for GEFS mode (physics perturbation
            # is additive, not required)
        else:
            if not self.parameters and self.perturb_physics:
                raise ValueError("No parameters defined for perturbation.")
        for p in self.parameters:
            p.validate()


class ParamGenerator:
    """Generate perturbed parameter sets using Latin Hypercube Sampling.

    LHS divides each parameter's range into n equal strata, then randomly
    selects one sample from each stratum. This ensures better coverage of
    the parameter space than pure random sampling.

    Member 000 is always the control run (unperturbed defaults).
    Members 001..N-1 are perturbed.
    """

    def __init__(self, config: EnsembleConfig):
        self.config = config
        self.config.validate()

    def _get_atmospheric_source(self, member_id: str) -> Optional[Dict[str, Any]]:
        """Get atmospheric source config for a member, if atmospheric ensemble is enabled."""
        atm = self.config.atmospheric
        if not atm.enabled:
            return None
        member_cfg = atm.members.get(member_id)
        if member_cfg:
            return {
                "met_source_1": member_cfg.met_source_1,
                "met_source_2": member_cfg.met_source_2,
                "label": member_cfg.label,
            }
        # Members not listed in atmospheric_ensemble.members use defaults
        return None

    def _get_gefs_source(self, member_id: str) -> Optional[Dict[str, Any]]:
        """Get GEFS atmospheric source config for a member."""
        gefs = self.config.gefs
        if not gefs.enabled:
            return None
        member_cfg = gefs.members.get(member_id)
        if member_cfg:
            return {
                "met_source_1": member_cfg.met_source_1,
                "met_source_2": member_cfg.met_source_2,
                "label": member_cfg.label,
            }
        return None

    def _generate_lhs_params(
        self,
        rng,
        n_perturbed: int,
    ) -> List[Dict[str, float]]:
        """Generate LHS-perturbed physics parameters for n_perturbed members.

        Args:
            rng: Random number generator (seeded)
            n_perturbed: Number of perturbed members (excludes control)

        Returns:
            List of dicts mapping parameter name to perturbed value,
            one dict per perturbed member (index 0 = member 001, etc.)
        """
        n_params = len(self.config.parameters)
        if n_params == 0 or n_perturbed == 0:
            return [{} for _ in range(n_perturbed)]

        # Latin Hypercube Sampling
        lhs_samples = []
        for _ in range(n_params):
            perm = list(range(n_perturbed))
            rng.shuffle(perm)
            samples = []
            for i in range(n_perturbed):
                stratum = perm[i]
                u = (stratum + rng.random()) / n_perturbed
                samples.append(u)
            lhs_samples.append(samples)

        # Transform unit samples to physical parameter values
        all_params = []
        for i in range(n_perturbed):
            member_params = {}
            for j, p in enumerate(self.config.parameters):
                u = lhs_samples[j][i]
                if p.distribution == "uniform":
                    val = p.min_val + u * (p.max_val - p.min_val)
                elif p.distribution == "log_uniform":
                    log_min = math.log10(p.min_val)
                    log_max = math.log10(p.max_val)
                    val = 10 ** (log_min + u * (log_max - log_min))
                else:
                    val = p.min_val + u * (p.max_val - p.min_val)
                member_params[p.name] = val
            all_params.append(member_params)

        return all_params

    def generate(self) -> List[Dict[str, Any]]:
        """Generate parameter sets for all ensemble members.

        Returns:
            List of dicts, one per member. Each dict contains:
              - member_id: str (e.g., "000", "001")
              - is_control: bool
              - parameters: dict mapping param name to value
              - atmospheric_source: dict or null (if atmospheric/gefs ensemble enabled)
        """
        import random

        rng = random.Random(self.config.seed)
        n_perturbed = self.config.n_members - 1  # Exclude control

        # Dispatch to method-specific generator
        if self.config.method == "gefs":
            return self._generate_gefs(rng, n_perturbed)
        elif self.config.method == "atmospheric":
            return self._generate_atmospheric(rng, n_perturbed)
        else:
            return self._generate_parameter_perturbation(rng, n_perturbed)

    def _generate_gefs(
        self,
        rng,
        n_perturbed: int,
    ) -> List[Dict[str, Any]]:
        """Generate members with GEFS atmospheric sources + optional physics perturbation.

        Member 000 = control (GFS deterministic + default physics).
        Members 001+ = GEFS perturbation members + LHS-perturbed physics
        (if parameters section exists).
        """
        default_params = {
            p.name: p.default for p in self.config.parameters
        }

        members = []

        # Member 000: control
        members.append({
            "member_id": "000",
            "is_control": True,
            "parameters": dict(default_params),
            "atmospheric_source": self._get_gefs_source("000"),
        })

        if n_perturbed == 0:
            return members

        # Generate LHS physics perturbations for members 001+
        # (returns empty dicts if no parameters are defined)
        lhs_params = self._generate_lhs_params(rng, n_perturbed)

        for i in range(n_perturbed):
            member_id = f"{i + 1:03d}"
            # Start with default params, then override with LHS perturbations
            member_params = dict(default_params)
            if lhs_params[i]:
                member_params.update(lhs_params[i])

            members.append({
                "member_id": member_id,
                "is_control": False,
                "parameters": member_params,
                "atmospheric_source": self._get_gefs_source(member_id),
            })

        return members

    def _generate_atmospheric(
        self,
        rng,
        n_perturbed: int,
    ) -> List[Dict[str, Any]]:
        """Generate members with different atmospheric sources, default physics."""
        default_params = {
            p.name: p.default for p in self.config.parameters
        }
        members = []

        # Member 000: control
        members.append({
            "member_id": "000",
            "is_control": True,
            "parameters": dict(default_params),
            "atmospheric_source": self._get_atmospheric_source("000"),
        })

        for i in range(n_perturbed):
            member_id = f"{i + 1:03d}"
            members.append({
                "member_id": member_id,
                "is_control": False,
                "parameters": dict(default_params),
                "atmospheric_source": self._get_atmospheric_source(member_id),
            })

        return members

    def _generate_parameter_perturbation(
        self,
        rng,
        n_perturbed: int,
    ) -> List[Dict[str, Any]]:
        """Generate members with LHS physics perturbation + optional atmospheric ensemble."""
        members = []

        # Member 000: control
        members.append({
            "member_id": "000",
            "is_control": True,
            "parameters": {
                p.name: p.default for p in self.config.parameters
            },
            "atmospheric_source": self._get_atmospheric_source("000"),
        })

        if n_perturbed == 0:
            return members

        # Generate LHS physics perturbations
        lhs_params = self._generate_lhs_params(rng, n_perturbed)

        for i in range(n_perturbed):
            member_id = f"{i + 1:03d}"
            members.append({
                "member_id": member_id,
                "is_control": False,
                "parameters": lhs_params[i],
                "atmospheric_source": self._get_atmospheric_source(member_id),
            })

        return members

    def write_param_overrides(
        self,
        members: List[Dict[str, Any]],
        output_dir: str,
    ) -> List[str]:
        """Write parameter override files for each ensemble member.

        Creates one JSON file per member in output_dir/member_NNN/params.json.
        These can be read by the J-job to modify param.nml before model execution.

        Args:
            members: Output of generate()
            output_dir: Base directory for member subdirectories

        Returns:
            List of paths to the generated override files
        """
        paths = []
        for member in members:
            mid = member["member_id"]
            member_dir = os.path.join(output_dir, f"member_{mid}")
            os.makedirs(member_dir, exist_ok=True)

            override_file = os.path.join(member_dir, "params.json")
            with open(override_file, "w") as f:
                json.dump(member, f, indent=2)
            paths.append(override_file)

        return paths

    def format_summary(self, members: List[Dict[str, Any]]) -> str:
        """Format a human-readable summary of the ensemble members."""
        lines = []
        lines.append(f"Ensemble: {self.config.n_members} members "
                      f"(1 control + {self.config.n_members - 1} perturbed)")
        lines.append(f"Model type: {self.config.model_type}")
        lines.append(f"Method: {self.config.method}")
        lines.append(f"Seed: {self.config.seed}")
        lines.append(f"Physics perturbation: {'enabled' if self.config.perturb_physics else 'disabled'}")
        if self.config.parameters:
            lines.append(f"Parameters: {', '.join(p.name for p in self.config.parameters)}")
        if self.config.method == "gefs" and self.config.gefs.enabled:
            lines.append(f"GEFS ensemble: enabled "
                          f"(resolution: {self.config.gefs.resolution}, "
                          f"product: {self.config.gefs.product})")
            lines.append(f"GEFS extra sources: "
                          f"{', '.join(self.config.gefs.extra_sources)}")
        elif self.config.atmospheric.enabled:
            lines.append(f"Atmospheric ensemble: enabled "
                          f"(extra sources: {', '.join(self.config.atmospheric.extra_sources)})")
        lines.append("")

        # Determine if we should show atmospheric source column
        show_atmos = (
            self.config.atmospheric.enabled
            or (self.config.method == "gefs" and self.config.gefs.enabled)
        )

        # Header
        param_names = [p.name for p in self.config.parameters]
        header = f"{'Member':<10} {'Control':<10}"
        for name in param_names:
            header += f" {name:>12}"
        if show_atmos:
            header += f"  {'Atmos Source':<25}"
        lines.append(header)
        lines.append("-" * len(header))

        for m in members:
            line = f"{m['member_id']:<10} {'yes' if m['is_control'] else 'no':<10}"
            for name in param_names:
                val = m["parameters"].get(name)
                if val is not None:
                    line += f" {val:>12.6g}"
                else:
                    line += f" {'N/A':>12}"
            if show_atmos:
                atm = m.get("atmospheric_source")
                if atm:
                    line += f"  {atm['label']:<25}"
                else:
                    line += f"  {'default (GFS+HRRR)':<25}"
            lines.append(line)

        return "\n".join(lines)


def main():
    """Command-line interface for parameter generation."""
    parser = argparse.ArgumentParser(
        description="Generate ensemble parameter perturbations for NOS-OFS"
    )
    parser.add_argument(
        "ofs",
        help="OFS system name (e.g., secofs) or path to YAML config",
    )
    parser.add_argument(
        "n_members",
        nargs="?",
        type=int,
        default=None,
        help="Number of ensemble members (overrides YAML if provided)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed (overrides YAML if provided)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Write parameter override files to this directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable table",
    )
    args = parser.parse_args()

    # Resolve YAML path
    if os.path.isfile(args.ofs):
        yaml_path = args.ofs
    else:
        # Look in standard parm/systems/ location
        candidates = [
            os.path.join("parm", "systems", f"{args.ofs}.yaml"),
            os.path.join(
                os.environ.get("PARMnos", ""),
                "systems",
                f"{args.ofs}.yaml",
            ),
        ]
        home = os.environ.get("HOMEnos", "")
        if home:
            candidates.append(
                os.path.join(home, "parm", "systems", f"{args.ofs}.yaml")
            )
        yaml_path = None
        for c in candidates:
            if os.path.isfile(c):
                yaml_path = c
                break
        if yaml_path is None:
            print(f"ERROR: Cannot find YAML config for '{args.ofs}'", file=sys.stderr)
            print(f"Searched: {candidates}", file=sys.stderr)
            return 1

    config = EnsembleConfig.from_yaml(yaml_path)

    # Override from command line
    if args.n_members is not None:
        config.n_members = args.n_members
    if args.seed is not None:
        config.seed = args.seed

    generator = ParamGenerator(config)
    members = generator.generate()

    if args.json:
        print(json.dumps(members, indent=2))
    else:
        print(generator.format_summary(members))

    if args.output_dir:
        paths = generator.write_param_overrides(members, args.output_dir)
        print(f"\nWrote {len(paths)} parameter override files to {args.output_dir}/")
        for p in paths:
            print(f"  {p}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
