from typing import ClassVar

from .execution_policy import ExecutionMode
from .stofs_config import StofsConfig
from .stofs_model import StofsModel
from .stofs_task import StofsTask


class AdcircModel(StofsModel):
    """
    Class representing the ADCIRC model type in a STOFS workflow.
    """

    # Define the tasks used in the ADCIRC model and the execution type (LEGACY or PYTHON)
    TASK_LIST: ClassVar[dict] = {
        "prep_nowcast": StofsTask(
            "prep_nowcast", ExecutionMode.LEGACY, ["adcirc_prep_nowcast.sh"]
        ),
        "nowcast": StofsTask(
            "nowcast", ExecutionMode.LEGACY, ["adcirc_run_nowcast.sh"]
        ),
        "prep_forecast": StofsTask(
            "prep_forecast", ExecutionMode.LEGACY, ["adcirc_prep_forecast.sh"]
        ),
        "forecast": StofsTask(
            "forecast", ExecutionMode.LEGACY, ["adcirc_run_forecast.sh"]
        ),
        "post": StofsTask(
            "post",
            ExecutionMode.LEGACY,
            ["adcirc_run_postproc.sh"],
        ),
    }

    def __init__(self, config: StofsConfig) -> None:
        """
        Initialize the parent class (StofsModel) with the configuration.
        """
        super().__init__(config)

    def prep_nowcast(self) -> None:
        """
        Run the preparation step of the nowcast model.
        """
        if AdcircModel.TASK_LIST["prep_nowcast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(AdcircModel.TASK_LIST["prep_nowcast"])
        else:
            msg = f"prep_nowcast() is not implemented for execution mode {AdcircModel.TASK_LIST['prep_nowcast'].mode()}"
            raise NotImplementedError(msg)

    def run_nowcast(self) -> None:
        """
        Run the nowcast step of the model.
        """
        if AdcircModel.TASK_LIST["nowcast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(AdcircModel.TASK_LIST["nowcast"])
        else:
            msg = f"run_nowcast() is not implemented for execution mode {AdcircModel.TASK_LIST['run_nowcast'].mode()}"
            raise NotImplementedError(msg)

    def prep_forecast(self) -> None:
        """
        Run the preparation step of the forecast model.
        """
        if AdcircModel.TASK_LIST["prep_forecast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(AdcircModel.TASK_LIST["prep_forecast"])
        else:
            msg = f"prep_nowcast() is not implemented for execution mode {AdcircModel.TASK_LIST['prep_forecast'].mode()}"
            raise NotImplementedError(msg)

    def run_forecast(self) -> None:
        """
        Run the forecast step of the model.
        """
        if AdcircModel.TASK_LIST["forecast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(AdcircModel.TASK_LIST["forecast"])
        else:
            msg = f"run_nowcast() is not implemented for execution mode {AdcircModel.TASK_LIST['forecast'].mode()}"
            raise NotImplementedError(msg)

    def post(self) -> None:
        """
        Run the post-processing step of the model.
        """
        if AdcircModel.TASK_LIST["post"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(AdcircModel.TASK_LIST["post"])
        else:
            msg = f"post() is not implemented for execution mode {AdcircModel.TASK_LIST['post'].mode()}"
            raise NotImplementedError(msg)
