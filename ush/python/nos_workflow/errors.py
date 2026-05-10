"""Exception hierarchy for nos_workflow.

These map to NCO ``err_chk`` / ``err_exit`` semantics: a top-level handler
in ``cli.main`` catches ``WorkflowError``, logs a one-line FATAL to stdout
(so on-call sees it in ``OUTPUT.$$``), writes the full traceback to a
side file, and exits non-zero so PBS marks the job FAILED.
"""


class WorkflowError(Exception):
    """Base for all nos_workflow exceptions. Operationally fatal."""


class ConfigError(WorkflowError):
    """YAML / NCO env config is invalid or inconsistent."""


class StageNotFoundError(WorkflowError):
    """The requested ``(ofs, stage)`` pair is not registered."""


class OFSNotRegisteredError(WorkflowError):
    """No descriptor exists for the requested OFS name."""


class StageFailedError(WorkflowError):
    """A stage's runtime body raised. Wrap with the stage name + return code."""

    def __init__(self, stage: str, ofs: str, returncode: int = 1, msg: str = ""):
        self.stage = stage
        self.ofs = ofs
        self.returncode = returncode
        super().__init__(
            f"stage={stage} ofs={ofs} rc={returncode}"
            + (f": {msg}" if msg else "")
        )
