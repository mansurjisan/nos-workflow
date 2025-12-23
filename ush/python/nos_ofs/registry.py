"""
OFS Registry and Factory

Provides a factory for creating OFS model instances based on system name.
Automatically selects the correct model implementation (SCHISM, FVCOM, ROMS).
"""

from pathlib import Path
from typing import Dict, Type, Optional

from .config.config_legacy import OFSConfig
from .base_model import BaseModel, ModelType


class OFSRegistry:
    """
    Registry for all operational forecast systems.

    Provides factory methods to create model instances from OFS names,
    automatically selecting the correct model implementation.

    Usage:
        # Create any OFS model by name
        model = OFSRegistry.create_model("stofs_3d_atl")
        model = OFSRegistry.create_model("cbofs")
        model = OFSRegistry.create_model("leofs")

        # List available OFS systems
        print(OFSRegistry.list_available())
    """

    # Mapping of OFS names to model types
    OFS_MODEL_TYPES: Dict[str, ModelType] = {
        # SCHISM-based systems
        "stofs_3d_atl": ModelType.SCHISM,
        "stofs_3d_pac": ModelType.SCHISM,
        "secofs": ModelType.SCHISM,
        "creofs": ModelType.SCHISM,

        # FVCOM-based systems (Great Lakes)
        "leofs": ModelType.FVCOM,
        "loofs": ModelType.FVCOM,
        "lmhofs": ModelType.FVCOM,
        "lsofs": ModelType.FVCOM,
        "ngofs2": ModelType.FVCOM,
        "sfbofs": ModelType.FVCOM,
        "sscofs": ModelType.FVCOM,

        # ROMS-based systems
        "cbofs": ModelType.ROMS,
        "dbofs": ModelType.ROMS,
        "tbofs": ModelType.ROMS,
        "gomofs": ModelType.ROMS,
        "ciofs": ModelType.ROMS,
        "wcofs": ModelType.ROMS,
        "wcofs_da": ModelType.ROMS,
        "wcofs_free": ModelType.ROMS,
    }

    # Cache for model classes (lazy loaded)
    _model_classes: Dict[ModelType, Type[BaseModel]] = {}

    @classmethod
    def create_model(
        cls,
        ofs_name: str,
        config: OFSConfig = None,
        config_file: str = None,
    ) -> BaseModel:
        """
        Create a model instance for the specified OFS.

        Args:
            ofs_name: OFS system name (e.g., 'stofs_3d_atl', 'cbofs')
            config: Pre-loaded OFSConfig (optional)
            config_file: Path to YAML config file (optional)

        Returns:
            Model instance (SCHISMModel, FVCOMModel, or ROMSModel)

        Raises:
            ValueError: If OFS name is unknown
        """
        ofs_name = ofs_name.lower()

        if ofs_name not in cls.OFS_MODEL_TYPES:
            available = ", ".join(sorted(cls.OFS_MODEL_TYPES.keys()))
            raise ValueError(f"Unknown OFS: {ofs_name}. Available: {available}")

        model_type = cls.OFS_MODEL_TYPES[ofs_name]

        # Load config if not provided
        if config is None:
            if config_file:
                config = OFSConfig.from_yaml(config_file)
            else:
                # Try to find default config
                config_file = cls._find_ofs_config(ofs_name)
                if config_file:
                    config = OFSConfig.from_yaml(str(config_file))
                else:
                    config = OFSConfig.from_environment()
                    config.RUN = ofs_name

        # Get model class
        model_class = cls._get_model_class(model_type)

        return model_class(config)

    @classmethod
    def _get_model_class(cls, model_type: ModelType) -> Type[BaseModel]:
        """Get or import the model class for a model type."""
        if model_type not in cls._model_classes:
            if model_type == ModelType.SCHISM:
                from .models.schism import SCHISMModel
                cls._model_classes[model_type] = SCHISMModel
            elif model_type == ModelType.FVCOM:
                from .models.fvcom import FVCOMModel
                cls._model_classes[model_type] = FVCOMModel
            elif model_type == ModelType.ROMS:
                from .models.roms import ROMSModel
                cls._model_classes[model_type] = ROMSModel
            else:
                raise ValueError(f"Unsupported model type: {model_type}")

        return cls._model_classes[model_type]

    @classmethod
    def _find_ofs_config(cls, ofs_name: str) -> Optional[Path]:
        """Find the default YAML config for an OFS."""
        # Look in ofs/ directory
        ofs_dir = Path(__file__).parent / "ofs"
        config_file = ofs_dir / f"{ofs_name}.yaml"
        if config_file.exists():
            return config_file
        return None

    @classmethod
    def get_model_type(cls, ofs_name: str) -> ModelType:
        """
        Get the model type for an OFS.

        Args:
            ofs_name: OFS system name

        Returns:
            ModelType enum value
        """
        ofs_name = ofs_name.lower()
        if ofs_name not in cls.OFS_MODEL_TYPES:
            raise ValueError(f"Unknown OFS: {ofs_name}")
        return cls.OFS_MODEL_TYPES[ofs_name]

    @classmethod
    def list_available(cls) -> Dict[str, str]:
        """
        List all available OFS systems.

        Returns:
            Dictionary mapping OFS names to model types
        """
        return {name: mtype.value for name, mtype in cls.OFS_MODEL_TYPES.items()}

    @classmethod
    def list_by_model_type(cls, model_type: ModelType) -> list:
        """
        List OFS systems for a specific model type.

        Args:
            model_type: Model type to filter by

        Returns:
            List of OFS names using that model
        """
        return [
            name for name, mtype in cls.OFS_MODEL_TYPES.items()
            if mtype == model_type
        ]

    @classmethod
    def register_ofs(cls, ofs_name: str, model_type: ModelType) -> None:
        """
        Register a new OFS system.

        Args:
            ofs_name: OFS system name
            model_type: Model type for the OFS
        """
        cls.OFS_MODEL_TYPES[ofs_name.lower()] = model_type
