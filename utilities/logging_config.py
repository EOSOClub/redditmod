import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logging():
    """
    Sets up structured JSON logging for the application.
    """
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers to avoid duplicate logs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Use a stream handler to output to stdout
    log_handler = logging.StreamHandler(sys.stdout)

    # Define the format of the JSON logs
    # Including standard log record attributes, plus any 'extra' passed to the logger
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s'
    )

    log_handler.setFormatter(formatter)
    root_logger.addHandler(log_handler)

    # --- Optional: Quieter logging for noisy libraries ---
    # For example, reduce the verbosity of the 'prawcore' library
    logging.getLogger("prawcore").setLevel(logging.WARNING)

    logging.info("Structured JSON logging configured.")

