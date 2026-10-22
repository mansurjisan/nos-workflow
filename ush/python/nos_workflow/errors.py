"""Exception hierarchy for nos_workflow."""


class WorkflowError(Exception):
    """Base for all nos_workflow exceptions."""


class ConfigError(WorkflowError):
    """YAML / NCO env config is invalid or inconsistent."""


class StageNotFoundError(WorkflowError):
    """The requested ``(ofs, stage)`` pair is not registered."""


class OFSNotRegisteredError(WorkflowError):
    """No descriptor exists for the requested OFS name."""


class StageFailedError(WorkflowError):
    """A stage's runtime body raised."""

    def __init__(self, stage: str, ofs: str, returncode: int = 1, msg: str = ""):
        self.stage = stage
        self.ofs = ofs
        self.returncode = returncode
        super().__init__(
            f"stage={stage} ofs={ofs} rc={returncode}"
            + (f": {msg}" if msg else "")
        )
