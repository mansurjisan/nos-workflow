from dataclasses import dataclass, field
from enum import Enum


class ExecutionMode(Enum):
    """
    Execution modes for the STOfS workflow manager tasks.
    """

    UNKNOWN = 0
    LEGACY = 1
    PYTHON = 2

    def __str__(self) -> str:
        """
        Return the name of the execution mode as a string.

        Returns:
            str: The name of the execution mode.
        """
        return self.name


class ExecutionPolicy(Enum):
    """
    Execution policies for the STOfS workflow manager.
    """

    UNKNOWN = 0
    SERIAL = 1
    PARALLEL = 2

    def __str__(self) -> str:
        """
        Return the name of the execution policy as a string.

        Returns:
            str: The name of the execution policy.
        """
        return self.name


@dataclass
class ExecutionAttributes:
    """
    Attributes for execution policies.
    """

    policy: ExecutionPolicy = field(default=ExecutionPolicy.SERIAL)
    num_processes: int = field(default=1)
