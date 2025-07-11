from __future__ import annotations

from enum import Enum


class ModelType(Enum):
    """
    Enum representing the type of model used in the STOfS workflow manager.
    """

    UNKNOWN_MODEL = 0
    ADCIRC_MODEL = 1
    SCHISM_MODEL = 2

    @staticmethod
    def from_string(model_type: str) -> ModelType:
        """
        Convert a string to a ModelType enum.

        Args:
            model_type (str): The string representation of the model type.

        Returns:
            ModelType: The corresponding ModelType enum.
        """
        if model_type.upper() == "ADCIRC":
            return ModelType.ADCIRC_MODEL
        if model_type.upper() == "SCHISM":
            return ModelType.SCHISM_MODEL
        return ModelType.UNKNOWN_MODEL
