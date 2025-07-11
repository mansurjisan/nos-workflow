import logging

STOFS_LOG = logging.getLogger("StofsWorkflow")


def setup_stofs_logging() -> None:
    """
    Setup the logging configuration for the STOFS workflow.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s :: %(levelname)s :: %(name)s :: %(filename)s:%(lineno)d :: %(message)s",
    )


def get_stofs_logger() -> logging.Logger:
    """
    Get the logger for the STOfS workflow.

    Returns:
        logging.Logger: The logger for the STOfS workflow.
    """
    return STOFS_LOG
