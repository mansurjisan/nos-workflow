import os
import tempfile

import yaml

from StofsWorkflow.adcircmodel import AdcircModel
from StofsWorkflow.model_factory import model_factory
from StofsWorkflow.model_type import ModelType
from StofsWorkflow.stofs_config import StofsConfig
from StofsWorkflow.stofs_logger import setup_stofs_logging

setup_stofs_logging()


def test_adcirc_execution() -> None:
    """
    Test the execution of the ADCIRC model.
    """
    working_directory = os.path.join(os.getcwd(), "examples", "scripts")

    config_data = {
        "type": "ADCIRC",
        "name": "test-adcirc-model",
        "version": "1.0",
        "script_directory": working_directory,
    }

    with tempfile.NamedTemporaryFile(delete=True, suffix=".yaml") as temp_file:
        with open(temp_file.name, "w") as f:
            yaml.dump(config_data, f)

        temp_file_path = temp_file.name
        model = model_factory(StofsConfig(temp_file_path))

        assert isinstance(model, AdcircModel), "Model is not of type AdcircModel"
        assert (
            model.config().model_name == "test-adcirc-model"
        ), "Model name does not match"
        assert (
            model.config().model_type == ModelType.ADCIRC_MODEL
        ), "Model type does not match"
        assert model.config().model_version == "1.0", "Model version does not match"

        # Run the model
        model.prep_nowcast()
        model.run_nowcast()
        model.prep_forecast()
        model.run_forecast()
        model.post()
