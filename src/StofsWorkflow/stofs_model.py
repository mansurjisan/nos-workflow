import os
import subprocess

from .execution_policy import ExecutionAttributes, ExecutionMode, ExecutionPolicy
from .model_type import ModelType
from .stofs_config import StofsConfig
from .stofs_logger import get_stofs_logger
from .stofs_task import StofsTask

log = get_stofs_logger()


class StofsModel:
    """
    Class representing a model type in a STOFS workflow.
    """

    def __init__(self, config: StofsConfig) -> None:
        """
        Initialize the StofsModel with the specified configuration.
        """
        self.__config = config

    def __repr__(self) -> str:
        """
        String representation of the StofsModel instance.
        """
        return f"StofsModel(type={self.type()}, name={self.config().model_name}, version={self.config().model_version})"

    def config(self) -> StofsConfig:
        """
        Gets the configuration object used for this model instance

        Returns:
            StofsConfig: The configuration object used for this model instance
        """
        return self.__config

    def type(self) -> ModelType:
        """
        Get the type of the model.

        Returns:
            ModelType: The type of the model.
        """
        return self.__config.model_type

    def prep_nowcast(self) -> None:
        """
        Run the preparation step of the nowcast model.
        """
        msg = "Subclasses must implement prep_nowcast()"
        raise NotImplementedError(msg)

    def run_nowcast(self) -> None:
        """
        Run the nowcast step of the model.
        """
        msg = "Subclasses must implement run_nowcast()"
        raise NotImplementedError(msg)

    def prep_forecast(self) -> None:
        """
        Run the preparation step of the forecast model.
        """
        msg = "Subclasses must implement prep_forecast()"
        raise NotImplementedError(msg)

    def run_forecast(self) -> None:
        """
        Run the forecast step of the model.
        """
        msg = "Subclasses must implement run_forecast()"
        raise NotImplementedError(msg)

    def post(self) -> None:
        """
        Run the post-processing step of the model.
        """
        msg = "Subclasses must implement post()"
        raise NotImplementedError(msg)

    def _run_legacy(self, task: StofsTask) -> None:
        """
        Run a legacy scripted task

        Args:
            task (StofsTask): The task to run.
        """
        if task.mode() == ExecutionMode.LEGACY:
            if task.legacy_task_list() is None:
                msg = f"No legacy tasks exist for {self.type()}:{task.name()}"
                raise ValueError(msg)
            else:
                for script in task.legacy_task_list():
                    self._run_script(
                        script, ExecutionAttributes(policy=ExecutionPolicy.SERIAL)
                    )
        else:
            msg = f"Task {task.name()} is not in LEGACY mode"
            raise ValueError(msg)

    def _run_script(
        self,
        script: str,
        execution_attributes: ExecutionAttributes = ExecutionAttributes,
    ) -> None:
        """
        Run a script with the specified execution policy.

        Args:
            script (str): The script to run.
            execution_attributes (ExecutionAttributes): The execution attributes for the script
        """
        import os

        script_path = os.path.join(self.__config.script_directory, script)
        StofsModel.__run_script_serial(script_path, execution_attributes)

    @staticmethod
    def __run_script_serial(
        script_path: str, execution_attributes: ExecutionAttributes
    ) -> None:
        """
        Run a script in serial.

        Args:
            script_path (str): The path to the script to run.
            execution_attributes (ExecutionAttributes): The execution attributes for serial
        """
        if not os.path.exists(script_path):
            msg = f"Script {script_path} does not exist."
            raise FileNotFoundError(msg)

        log.debug(f"Running script {script_path} in serial mode.")

        log.info("----BEGIN SCRIPT OUTPUT----")
        return_data = subprocess.run(
            script_path, shell=False, capture_output=False, check=False
        )
        log.info("----END SCRIPT OUTPUT----")

        if return_data.returncode != 0:
            msg = (
                f"Script {script_path} failed with return code {return_data.returncode}"
            )
            raise RuntimeError(msg)

    @staticmethod
    def __run_script_parallel(
        script_path: str, execution_attributes: ExecutionAttributes
    ) -> None:
        """
        Run a script in parallel.

        Args:
            script_path (str): The path to the script to run.
            execution_attributes (ExecutionAttributes): The execution attributes for parallel
        """
        log.info(f"Running script {script_path} in parallel mode.")
        command = ["mpirun", "-n", str(execution_attributes.num_processes), script_path]
        return_data = subprocess.run(
            command, shell=False, capture_output=False, check=False
        )

        if return_data.returncode != 0:
            msg = (
                f"Script {script_path} failed with return code {return_data.returncode}"
            )
            raise RuntimeError(msg)
