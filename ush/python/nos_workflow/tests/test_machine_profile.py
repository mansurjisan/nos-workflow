"""Machine profile schema, credential precedence, and Slurm rendering."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
MACHINES = REPO / "parm" / "machines"

sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.platform import (  # noqa: E402
    JobSpec, KIND_MODEL, KIND_SERIAL, MachineProfile, ProfileError,
    available_machines, render_directives, render_mpi_argv,
)


def _load(machine, **kw):
    kw.setdefault("machines_dir", MACHINES)
    kw.setdefault("env", {})
    return MachineProfile.load(machine, **kw)


class TestShippedProfiles:
    def test_both_profiles_exist(self):
        assert {"wcoss2", "hercules"} <= set(available_machines(MACHINES))

    def test_wcoss2_loads_with_committed_defaults(self):
        """WCOSS2 keeps ESTOFS-DEV/dev as compatibility defaults so the frozen
        baseline stays identical."""
        p = _load("wcoss2")
        assert (p.scheduler_type, p.account, p.queue) == ("pbs", "ESTOFS-DEV", "dev")
        assert (p.allocation.cores_per_node, p.allocation.ranks_per_node) == (128, 120)
        assert p.allocation.emit_ranks_per_node is True

    def test_hercules_requires_an_account(self):
        """account is null on purpose: the valid value depends on the user's
        project association, so it must fail before submission, not default."""
        with pytest.raises(ProfileError, match="requires account"):
            _load("hercules")

    def test_hercules_loads_once_account_supplied(self):
        p = _load("hercules", env={"NOS_ACCOUNT": "nosofs"})
        assert (p.scheduler_type, p.partition, p.account) == ("slurm", "hercules", "nosofs")
        assert p.qos is None                      # site association picks
        assert p.allocation.emit_ranks_per_node is True

    def test_unknown_machine_lists_alternatives(self):
        with pytest.raises(ProfileError, match="Available:"):
            _load("atlantis")


class TestCredentialPrecedence:
    """CLI > NOS_* env > overlay > machine default > fatal."""

    def test_env_beats_machine_default(self):
        p = _load("wcoss2", env={"NOS_ACCOUNT": "FROM_ENV"})
        assert p.account == "FROM_ENV"

    def test_overlay_beats_machine_default(self):
        p = _load("wcoss2", overlay={"account": "FROM_OVERLAY"})
        assert p.account == "FROM_OVERLAY"

    def test_env_beats_overlay(self):
        p = _load("wcoss2", env={"NOS_ACCOUNT": "FROM_ENV"},
                  overlay={"account": "FROM_OVERLAY"})
        assert p.account == "FROM_ENV"

    def test_explicit_override_beats_everything(self):
        p = _load("wcoss2", overrides={"account": "FROM_CLI"},
                  env={"NOS_ACCOUNT": "FROM_ENV"},
                  overlay={"account": "FROM_OVERLAY"})
        assert p.account == "FROM_CLI"

    def test_partition_override(self):
        p = _load("hercules", env={"NOS_ACCOUNT": "a", "NOS_PARTITION": "service"})
        assert p.partition == "service"

    def test_qos_override(self):
        p = _load("hercules", env={"NOS_ACCOUNT": "a", "NOS_QOS": "debug"})
        assert p.qos == "debug"


class TestSchemaGuards:
    BASE = {
        "machine": "t",
        "scheduler": {"type": "slurm", "account": "a"},
        "allocation": {"cores_per_node": 80, "ranks_per_node": 80},
        "mpi": {"launcher": "srun", "total_ranks_flag": "--ntasks"},
    }

    def _mk(self, **patch):
        import copy
        d = copy.deepcopy(self.BASE)
        for k, v in patch.items():
            d[k] = {**d.get(k, {}), **v} if isinstance(v, dict) else v
        return d

    def test_empty_ranks_per_node_flag_rejected(self):
        """The ambiguous sentinel this schema exists to avoid."""
        with pytest.raises(ProfileError, match="never an empty string"):
            MachineProfile.from_dict(
                self._mk(mpi={"ranks_per_node_flag": ""}), env={})

    def test_fixed_args_as_string_rejected(self):
        with pytest.raises(ProfileError, match="must be a list"):
            MachineProfile.from_dict(
                self._mk(mpi={"fixed_args": "--label --export=ALL"}), env={})

    def test_empty_fixed_arg_rejected(self):
        with pytest.raises(ProfileError, match="empty argv element"):
            MachineProfile.from_dict(
                self._mk(mpi={"fixed_args": ["--label", ""]}), env={})

    def test_ranks_exceeding_cores_rejected(self):
        with pytest.raises(ProfileError, match="exceeds"):
            MachineProfile.from_dict(
                self._mk(allocation={"cores_per_node": 80, "ranks_per_node": 96}), env={})

    def test_bad_scheduler_type_rejected(self):
        with pytest.raises(ProfileError, match="must be 'pbs' or 'slurm'"):
            MachineProfile.from_dict(self._mk(scheduler={"type": "lsf"}), env={})


class TestNodeMath:
    @pytest.mark.parametrize("ranks,wcoss2_nodes,hercules_nodes", [
        (2914, 25, 37),
        (4434, 37, 56),
        (4320, 36, 54),
        (3960, 33, 50),
    ])
    def test_node_counts(self, ranks, wcoss2_nodes, hercules_nodes):
        assert _load("wcoss2").nodes(ranks) == wcoss2_nodes
        assert _load("hercules", env={"NOS_ACCOUNT": "a"}).nodes(ranks) == hercules_nodes

    def test_zero_ranks_rejected(self):
        with pytest.raises(ProfileError, match="must be >= 1"):
            _load("wcoss2").nodes(0)


class TestHerculesRendering:
    @pytest.fixture
    def herc(self):
        return _load("hercules", env={"NOS_ACCOUNT": "nosofs"})

    def test_ranks_per_node_emitted_in_directives(self, herc):
        """emit_ranks_per_node: true emits --ntasks-per-node and omits a
        redundant --ntasks -- the pattern a working ufs-coastal card on
        Hercules submits with."""
        lines = render_directives(
            JobSpec(name="j", walltime="01:30:00", kind=KIND_MODEL, total_ranks=2914),
            herc,
        )
        assert "#SBATCH --nodes=37" in lines
        assert "#SBATCH --ntasks-per-node=80" in lines
        assert not any(l.startswith("#SBATCH --ntasks=") for l in lines)
        assert "#SBATCH --exclusive" in lines

    def test_mpi_argv_uses_bare_ranks_flag(self, herc):
        """srun receives total ranks only (-n); no ranks-per-node flag is
        passed to the launcher even though the SBATCH header carries one."""
        argv = render_mpi_argv(
            JobSpec(name="j", walltime="01:30:00", total_ranks=2914), herc, "pschism",
        )
        assert argv == ["srun", "-n", "2914", "--label", "pschism"]
        assert all(a != "" for a in argv)

    def test_qos_omitted_when_unset(self, herc):
        lines = render_directives(JobSpec(name="j", walltime="01:00:00"), herc)
        assert not any("--qos" in l for l in lines)

    def test_qos_emitted_when_set(self):
        p = _load("hercules", env={"NOS_ACCOUNT": "a", "NOS_QOS": "batch"})
        lines = render_directives(JobSpec(name="j", walltime="01:00:00"), p)
        assert "#SBATCH --qos=batch" in lines

    def test_directive_order_matches_working_card(self):
        """Exact field order proven on a working ufs-coastal card on
        Hercules: job-name, account, qos, partition, nodes, ntasks-per-node,
        exclusive, time, output, error."""
        p = _load("hercules", env={"NOS_ACCOUNT": "nos-surge", "NOS_QOS": "batch"})
        lines = render_directives(
            JobSpec(name="secofs_ufs_nc_00", walltime="01:30:00",
                    kind=KIND_MODEL, total_ranks=2914),
            p,
        )
        assert lines == [
            "#SBATCH --job-name=secofs_ufs_nc_00",
            "#SBATCH --account=nos-surge",
            "#SBATCH --qos=batch",
            "#SBATCH --partition=hercules",
            "#SBATCH --nodes=37",
            "#SBATCH --ntasks-per-node=80",
            "#SBATCH --exclusive",
            "#SBATCH --time=01:30:00",
            "#SBATCH --output=/dev/null",
            "#SBATCH --error=/dev/null",
        ]

    def test_serial_job_is_single_node(self, herc):
        lines = render_directives(
            JobSpec(name="prep", walltime="02:00:00", kind=KIND_SERIAL, cpus=8), herc,
        )
        assert "#SBATCH --nodes=1" in lines
        assert "#SBATCH --ntasks=8" in lines


def test_wcoss2_argv_is_unchanged_from_todays_command():
    """The exact string in ush/nos_run.sh today."""
    argv = render_mpi_argv(
        JobSpec(name="j", walltime="01:00:00", total_ranks=2914),
        _load("wcoss2"), "fv3_coastalS.exe",
    )
    assert argv == [
        "mpiexec", "-n", "2914", "-ppn", "120", "--cpu-bind", "core", "fv3_coastalS.exe",
    ]
