from enum import Enum


class Stage(Enum):
    """
    Stages of the STOfS workflow manager.
    """

    UNKNOWN = 0
    PREP_NOWCAST = 1
    NOWCAST = 2
    PREP_FORECAST = 3
    FORECAST = 4
    POST = 5

    def __str__(self) -> str:
        """
        Get the string representation of the stage.

        Returns:
            str: The string representation of the stage.
        """
        return self.name
