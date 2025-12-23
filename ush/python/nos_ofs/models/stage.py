"""
STOFS Workflow Stage Definitions

Defines the workflow stages for STOFS 3D Atlantic matching the
IT-STOFS operational ecFlow suite structure.
"""

from enum import Enum, auto


class Stage(Enum):
    """
    Workflow stages for STOFS 3D Atlantic.

    These stages match the IT-STOFS operational ecFlow suite:
    - prep_nowcast: Prepare all forcing data
    - now_forecast: Run combined nowcast and forecast simulation
    - post_1: Post-processing part 1 (2D fields, station data)
    - post_2: Post-processing part 2 (3D fields, graphics)
    - temp_salt_restart: T/S restart update from RTOFS
    """

    PREP_NOWCAST = auto()
    NOW_FORECAST = auto()
    POST_1 = auto()
    POST_2 = auto()
    TEMP_SALT_RESTART = auto()

    @classmethod
    def from_string(cls, stage_name: str) -> "Stage":
        """
        Get Stage enum from string name.

        Args:
            stage_name: Stage name (case-insensitive)

        Returns:
            Stage enum value

        Raises:
            ValueError: If stage name is invalid
        """
        name_map = {
            "prep_nowcast": cls.PREP_NOWCAST,
            "now_forecast": cls.NOW_FORECAST,
            "post_1": cls.POST_1,
            "post_2": cls.POST_2,
            "temp_salt_restart": cls.TEMP_SALT_RESTART,
        }
        normalized = stage_name.lower().strip()
        if normalized not in name_map:
            valid = ", ".join(name_map.keys())
            raise ValueError(f"Invalid stage: {stage_name}. Valid stages: {valid}")
        return name_map[normalized]

    def __str__(self) -> str:
        """Return lowercase stage name."""
        return self.name.lower()
