"""
Ensemble Parameter Generator

Generates perturbed parameter sets for ensemble model runs using
Latin Hypercube Sampling (LHS). Member 000 is always the control
run with unperturbed default values.

Supports two distribution types:
  - uniform:     Linear uniform sampling between [min, max]
  - log_uniform: Uniform sampling in log10 space (good for parameters
                 spanning orders of magnitude, e.g., mixing coefficients)

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
class EnsembleConfig:
    """Configuration for an ensemble run."""
    n_members: int
    method: str
    seed: int
    parameters: List[ParameterDef] = field(default_factory=list)

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

        params = []
        for name, pdef in ens.get("parameters", {}).items():
            params.append(ParameterDef(
                name=name,
                min_val=float(pdef["min"]),
                max_val=float(pdef["max"]),
                default=float(pdef.get("default", (pdef["min"] + pdef["max"]) / 2)),
                distribution=pdef.get("distribution", "uniform"),
                description=pdef.get("description", ""),
            ))

        return cls(
            n_members=int(ens.get("n_members", 5)),
            method=ens.get("method", "parameter_perturbation"),
            seed=int(ens.get("seed", 42)),
            parameters=params,
        )

    def validate(self):
        """Validate the ensemble configuration."""
        if self.n_members < 2:
            raise ValueError(
                f"n_members must be >= 2 (got {self.n_members}). "
                "Need at least control + 1 perturbed member."
            )
        if not self.parameters:
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

    def generate(self) -> List[Dict[str, Any]]:
        """Generate parameter sets for all ensemble members.

        Returns:
            List of dicts, one per member. Each dict contains:
              - member_id: str (e.g., "000", "001")
              - is_control: bool
              - parameters: dict mapping param name to value
        """
        import random

        rng = random.Random(self.config.seed)
        n_perturbed = self.config.n_members - 1  # Exclude control
        n_params = len(self.config.parameters)

        members = []

        # Member 000: control (unperturbed defaults)
        control = {
            "member_id": "000",
            "is_control": True,
            "parameters": {
                p.name: p.default for p in self.config.parameters
            },
        }
        members.append(control)

        if n_perturbed == 0:
            return members

        # Latin Hypercube Sampling for perturbed members
        # For each parameter, divide [0, 1] into n_perturbed equal strata
        # and sample one point from each stratum
        lhs_samples = []
        for _ in range(n_params):
            # Create strata permutation
            perm = list(range(n_perturbed))
            rng.shuffle(perm)
            # Sample one uniform value within each stratum
            samples = []
            for i in range(n_perturbed):
                stratum = perm[i]
                u = (stratum + rng.random()) / n_perturbed
                samples.append(u)
            lhs_samples.append(samples)

        # Transform unit samples to physical parameter values
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

            members.append({
                "member_id": f"{i + 1:03d}",
                "is_control": False,
                "parameters": member_params,
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
        lines.append(f"Method: {self.config.method}")
        lines.append(f"Seed: {self.config.seed}")
        lines.append(f"Parameters: {', '.join(p.name for p in self.config.parameters)}")
        lines.append("")

        # Header
        param_names = [p.name for p in self.config.parameters]
        header = f"{'Member':<10} {'Control':<10}"
        for name in param_names:
            header += f" {name:>12}"
        lines.append(header)
        lines.append("-" * len(header))

        for m in members:
            line = f"{m['member_id']:<10} {'yes' if m['is_control'] else 'no':<10}"
            for name in param_names:
                val = m["parameters"][name]
                line += f" {val:>12.6g}"
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
