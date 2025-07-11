import argparse
import sys

from .executor import (
    execute_forecast,
    execute_nowcast,
    execute_post,
    execute_prep_forecast,
    execute_prep_nowcast,
)


def generate_prep_nowcast_subparser(sp: argparse._SubParsersAction) -> None:
    """
    Command line interface for the prep1 workflow

    Args:
        sp: argparse._SubParsersAction object

    Returns:
        None
    """
    p = sp.add_parser("prep-nowcast", help="Prep Nowcast Workflow")
    p.add_argument(
        "--config", type=str, help="Path to the yaml configuration file", required=True
    )
    p.set_defaults(func=execute_prep_nowcast)


def generate_nowcast_subparser(sp: argparse._SubParsersAction) -> None:
    """
    Command line interface for the prep1 workflow

    Args:
        sp: argparse._SubParsersAction object

    Returns:
        None
    """
    p = sp.add_parser("nowcast", help="Nowcast Workflow")
    p.add_argument(
        "--config", type=str, help="Path to the yaml configuration file", required=True
    )
    p.set_defaults(func=execute_nowcast)


def generate_prep_forecast_subparser(sp: argparse._SubParsersAction) -> None:
    """
    Command line interface for the prep1 workflow

    Args:
        sp: argparse._SubParsersAction object

    Returns:
        None
    """
    p = sp.add_parser("prep-forecast", help="Prep Forecast Workflow")
    p.add_argument(
        "--config", type=str, help="Path to the yaml configuration file", required=True
    )
    p.set_defaults(func=execute_prep_forecast)


def generate_forecast_subparser(sp: argparse._SubParsersAction) -> None:
    """
    Command line interface for the prep1 workflow

    Args:
        sp: argparse._SubParsersAction object

    Returns:
        None
    """
    p = sp.add_parser("forecast", help="Forecast Workflow")
    p.add_argument(
        "--config", type=str, help="Path to the yaml configuration file", required=True
    )
    p.set_defaults(func=execute_forecast)


def generate_post_subparser(sp: argparse._SubParsersAction) -> None:
    """
    Command line interface for the prep1 workflow

    Args:
        sp: argparse._SubParsersAction object

    Returns:
        None
    """
    p = sp.add_parser("post", help="Post Workflow")
    p.add_argument(
        "--config", type=str, help="Path to the yaml configuration file", required=True
    )
    p.set_defaults(func=execute_post)


def stofs_cli() -> None:
    """
    Set up the initial CLI for the workflow manager.
    """
    import argparse

    from .stofs_logger import setup_stofs_logging

    setup_stofs_logging()

    p = argparse.ArgumentParser(description="STOFS Workflow Generator")
    sp = p.add_subparsers(dest="subparser")
    generate_prep_nowcast_subparser(sp)
    generate_nowcast_subparser(sp)
    generate_prep_forecast_subparser(sp)
    generate_forecast_subparser(sp)
    generate_post_subparser(sp)

    args = p.parse_args()

    # If the user did not provide a subparser, print the help message
    if not args.subparser:
        p.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    stofs_cli()
