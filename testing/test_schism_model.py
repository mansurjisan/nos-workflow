import os
import tempfile

import pytest
import yaml

from StofsWorkflow.model_factory import model_factory
from StofsWorkflow.model_type import ModelType
from StofsWorkflow.schismmodel import SchismModel
from StofsWorkflow.stofs_config import StofsConfig
from StofsWorkflow.stofs_logger import setup_stofs_logging

setup_stofs_logging()


def test_schism_execution() -> None:
    """
    Test the execution of the ADCIRC model.
    """
    working_directory = os.path.join(os.getcwd(), "examples", "scripts")

    config_data = {
        "type": "SCHISM",
        "name": "test-schism-model",
        "version": "2.0",
        "script_directory": working_directory,
    }

    with tempfile.NamedTemporaryFile(delete=True, suffix=".yaml") as temp_file:
        with open(temp_file.name, "w") as f:
            yaml.dump(config_data, f)

        temp_file_path = temp_file.name
        model = model_factory(StofsConfig(temp_file_path))

        assert isinstance(model, SchismModel), "Model is not of type SchismModel"
        assert (
            model.config().model_name == "test-schism-model"
        ), "Model name does not match"
        assert (
            model.config().model_type == ModelType.SCHISM_MODEL
        ), "Model type does not match"
        assert model.config().model_version == "2.0", "Model version does not match"

        # Run the model

        # We expect both of the following to fail
        with pytest.raises(ValueError):  # noqa: PT011
            model.prep_nowcast()

        with pytest.raises(ValueError):  # noqa: PT011
            model.run_nowcast()

        model.prep_forecast()
        model.run_forecast()
        model.post()
