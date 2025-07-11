import argparse

from .stofs_stage import Stage


def execute_prep_nowcast(args: argparse.Namespace) -> None:
    """
    Execute the prep_nowcast stage of the workflow.

    Args:
        args: Command line arguments.

    Returns:
        None
    """
    execute_stage(Stage.PREP_NOWCAST, args)


def execute_nowcast(args: argparse.Namespace) -> None:
    """
    Execute the nowcast stage of the workflow.

    Args:
        args: Command line arguments.

    Returns:
        None
    """
    execute_stage(Stage.NOWCAST, args)


def execute_prep_forecast(args: argparse.Namespace) -> None:
    """
    Execute the prep_forecast stage of the workflow.

    Args:
        args: Command line arguments.

    Returns:
        None
    """
    execute_stage(Stage.PREP_FORECAST, args)


def execute_forecast(args: argparse.Namespace) -> None:
    """
    Execute the forecast stage of the workflow.

    Args:
        args: Command line arguments.

    Returns:
        None
    """
    execute_stage(Stage.FORECAST, args)


def execute_post(args: argparse.Namespace) -> None:
    """
    Execute the post stage of the workflow.

    Args:
        args: Command line arguments.

    Returns:
        None
    """
    execute_stage(Stage.POST, args)


def execute_stage(stage: Stage, args: argparse.Namespace) -> None:
    """
    Execute the specified stage of the workflow.

    Args:
        stage: The stage to execute.
        args: Command line arguments.

    Returns:
        None
    """
    from .model_factory import model_factory
    from .stofs_config import StofsConfig

    config = StofsConfig(config_file=args.config)
    model = model_factory(config)

    if stage == Stage.PREP_NOWCAST:
        model.prep_nowcast()
    elif stage == Stage.NOWCAST:
        model.run_nowcast()
    elif stage == Stage.PREP_FORECAST:
        model.prep_forecast()
    elif stage == Stage.FORECAST:
        model.run_forecast()
    elif stage == Stage.POST:
        model.post()
    else:
        msg = f"Unknown stage: {stage}"
        raise ValueError(msg)
