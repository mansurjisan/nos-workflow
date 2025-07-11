from dataclasses import dataclass, field
from typing import Optional

from .model_type import ModelType


@dataclass(frozen=True)
class StofsConfig:
    """
    Class representing the configuration for a STOFS workflow.

    There is only one parameter passed in, everything else
    is derived during the __post_init__ method
    """

    config_file: Optional[str] = field(default=None)

    # These are derived from the config_file
    model_type: ModelType = field(default=ModelType.UNKNOWN_MODEL, init=False)
    model_name: str = field(default="Unknown", init=False)
    model_version: str = field(default="Unknown", init=False)
    script_directory: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        """
        This method is called after the object is initialized to load data
        from the YAML configuration file and validate it against the schema.
        """
        from yaml import safe_load

        from .stofs_schema import STOFS_SCHEMA

        with open(self.config_file) as f:
            config_data = safe_load(f)

        validated_input = STOFS_SCHEMA.validate(config_data)

        object.__setattr__(
            self, "model_type", ModelType.from_string(validated_input["type"])
        )
        object.__setattr__(self, "model_name", validated_input["name"])
        object.__setattr__(self, "model_version", validated_input["version"])
        object.__setattr__(
            self, "script_directory", validated_input["script_directory"]
        )
