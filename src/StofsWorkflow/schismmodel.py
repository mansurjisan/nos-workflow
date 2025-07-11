from typing import ClassVar

from .execution_policy import ExecutionMode
from .stofs_config import StofsConfig
from .stofs_model import StofsModel
from .stofs_task import StofsTask


class SchismModel(StofsModel):
    """
    Class representing the SCHISM model type in a STOFS workflow.
    """

    # Define the tasks used in the SCHISM model and the execution type (LEGACY or PYTHON)
    TASK_LIST: ClassVar[dict] = {
        "prep_nowcast": StofsTask("prep_nowcast", ExecutionMode.LEGACY, None),
        "nowcast": StofsTask("nowcast", ExecutionMode.LEGACY, None),
        "prep_forecast": StofsTask(
            "prep_forecast", ExecutionMode.LEGACY, ["JSTOFS_3D_ATL_PREP"]
        ),
        "forecast": StofsTask(
            "forecast", ExecutionMode.LEGACY, ["schism_run_forecast.sh"]
        ),
        "post": StofsTask(
            "post",
            ExecutionMode.LEGACY,
            ["JSTOFS_3D_ATL_POST_I"],
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
        if SchismModel.TASK_LIST["prep_nowcast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(SchismModel.TASK_LIST["prep_nowcast"])
        else:
            msg = f"prep_nowcast() is not implemented for execution mode {SchismModel.TASK_LIST['prep_nowcast'].mode()}"
            raise NotImplementedError(msg)

    def run_nowcast(self) -> None:
        """
        Run the nowcast step of the model.
        """
        if SchismModel.TASK_LIST["nowcast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(SchismModel.TASK_LIST["nowcast"])
        else:
            msg = f"run_nowcast() is not implemented for execution mode {SchismModel.TASK_LIST['run_nowcast'].mode()}"
            raise NotImplementedError(msg)

    def prep_forecast(self) -> None:
        """
        Run the preparation step of the forecast model.
        """
        if SchismModel.TASK_LIST["prep_forecast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(SchismModel.TASK_LIST["prep_forecast"])
        else:
            msg = f"prep_nowcast() is not implemented for execution mode {SchismModel.TASK_LIST['prep_forecast'].mode()}"
            raise NotImplementedError(msg)

    def run_forecast(self) -> None:
        """
        Run the forecast step of the model.
        """
        if SchismModel.TASK_LIST["forecast"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(SchismModel.TASK_LIST["forecast"])
        else:
            msg = f"run_nowcast() is not implemented for execution mode {SchismModel.TASK_LIST['forecast'].mode()}"
            raise NotImplementedError(msg)

    def post(self) -> None:
        """
        Run the post-processing step of the model.
        """
        if SchismModel.TASK_LIST["post"].mode() == ExecutionMode.LEGACY:
            self._run_legacy(SchismModel.TASK_LIST["post"])
        else:
            msg = f"post() is not implemented for execution mode {SchismModel.TASK_LIST['post'].mode()}"
            raise NotImplementedError(msg)
