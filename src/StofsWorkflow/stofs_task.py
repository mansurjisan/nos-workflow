from typing import Optional

from .execution_policy import ExecutionMode


class StofsTask:
    """
    Class representing a task (i.e. part of a simulation) in a STOFS workflow.
    """

    def __init__(
        self,
        task_name: str,
        task_mode: ExecutionMode,
        legacy_task_list: Optional[list[str]] = None,
    ) -> None:
        """
        Initialize the StofsTask with the specified task mode and legacy task list.

        Args:
            task_name (str): The name of the task.
            task_mode (ExecutionMode): The execution mode for the task.
            legacy_task_list (list[str], optional): A list of legacy tasks. Defaults to None.
        """
        self.__task_name = task_name
        self.__task_mode = task_mode
        self.__legacy_task_list = legacy_task_list

    def name(self) -> str:
        """
        Get the name of the task.

        Returns:
            str: The name of the task.
        """
        return self.__task_name

    def mode(self) -> ExecutionMode:
        """
        Get the execution mode of the task.

        Returns:
            ExecutionMode: The execution mode of the task.
        """
        return self.__task_mode

    def legacy_task_list(self) -> list[str]:
        """
        Get the list of legacy tasks.

        Returns:
            list[str]: The list of legacy tasks.
        """
        if self.__task_mode == ExecutionMode.LEGACY:
            return self.__legacy_task_list
        msg = "Legacy task list is only available in LEGACY mode."
        raise ValueError(msg)
