"""nos_workflow — operational workflow driver for NOS-OFS systems.

This is the package that owns the per-stage entry points and the CLI
(`nos run <stage> --ofs <name>`). It depends on `nos_utils` for forcing-
prep primitives and shells out to `mpiexec`/`module load` where shell
behavior matters; it never reimplements forcing math.

Layering rule:
    nos_workflow → nos_utils      (allowed)
    nos_utils → nos_workflow      (NEVER)
"""

__version__ = "0.1.0"
