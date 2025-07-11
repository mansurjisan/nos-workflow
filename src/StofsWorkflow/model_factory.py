from .adcircmodel import AdcircModel
from .model_type import ModelType
from .schismmodel import SchismModel
from .stofs_config import StofsConfig
from .stofs_model import StofsModel


def model_factory(config: StofsConfig) -> StofsModel:
    """
    Factory function to create a model instance based on the configuration object.
    """
    if config.model_type == ModelType.ADCIRC_MODEL:
        return AdcircModel(config)
    if config.model_type == ModelType.SCHISM_MODEL:
        return SchismModel(config)
    msg = f"Unknown model type: {config.model_type}"
    raise ValueError(msg)
