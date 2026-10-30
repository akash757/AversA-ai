import logging
import os
import sys

# ANSI Colors
COLORS = {
    "DEBUG": "\033[36m",      # Cyan
    "INFO": "\033[32m",       # Green
    "WARNING": "\033[33m",    # Yellow
    "ERROR": "\033[31m",      # Red
    "CRITICAL": "\033[1;31m", # Bold Red
    "RESET": "\033[0m",
    "DIM": "\033[2m",
}


class ColoredFormatter(logging.Formatter):
    """Custom Formatter to inject ANSI colors into log output."""

    def format(self, record: logging.LogRecord) -> str:
        color = COLORS.get(record.levelname, COLORS["RESET"])
        reset = COLORS["RESET"]
        dim = COLORS["DIM"]

        # Timestamp and level
        timestamp = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        level_label = f"{color}[{record.levelname}]{reset}"
        logger_name = f"{dim}[{record.name}]{reset}"

        message = record.getMessage()
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            message = f"{message}\n{record.exc_text}"

        return f"{dim}{timestamp}{reset} {level_label} {logger_name} {message}"


def setup_logger(name: str = "AversA_agent_ai") -> logging.Logger:
    """Configures and returns a logger instance with structured, colored formatting."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        env_level = os.getenv("LOG_LEVEL", "DEBUG" if os.getenv("ENV") != "production" else "INFO").upper()
        level = getattr(logging, env_level, logging.DEBUG)
        logger.setLevel(level)

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(ColoredFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    return logger


logger = setup_logger()

