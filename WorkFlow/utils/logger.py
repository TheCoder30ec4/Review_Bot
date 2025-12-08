import inspect
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock


class ColorFormatter(logging.Formatter):
    COLOR = {
        "DEBUG": "\033[94m",
        "INFO": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "CRITICAL": "\033[95m",
    }

    RESET = "\033[0m"

    def format(self, record):
        color = self.COLOR.get(record.levelname, self.RESET)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


class FileTrackingLogger:
    """Logger that tracks file transitions and creates separate log files per module."""

    def __init__(self):
        self.loggers = {}  # Cache of loggers per module
        self.file_handlers = {}  # Track file handlers per module
        self.previous_module = None  # Track previous module for transitions
        self.lock = Lock()  # Thread-safe access

        # Create logs directory in Backend directory (global)
        backend_dir = Path(__file__).parent.parent.parent
        self.logs_dir = backend_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)

        # Base logger for console output
        self.base_logger = logging.getLogger("Get_Your_Clothing")
        self.base_logger.setLevel(logging.DEBUG)

        # Console handler (shared across all loggers)
        if not any(
            isinstance(h, logging.StreamHandler) for h in self.base_logger.handlers
        ):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                ColorFormatter(
                    "[%(asctime)s] [%(levelname)s] %(filename)s:%(lineno)d → %(message)s"
                )
            )
            self.base_logger.addHandler(console_handler)

    def _get_calling_module_name(self):
        """Get the name of the module that called the logger."""
        frame = inspect.currentframe()
        try:
            # Go up the stack to find the caller (skip logger.py itself)
            for _ in range(10):  # Check up to 10 frames up
                frame = frame.f_back
                if frame is None:
                    break
                file_path = frame.f_globals.get("__file__", "")

                # Skip internal logging calls and this file
                if file_path and "logger.py" not in file_path:
                    # Extract file name from path
                    try:
                        module_file = Path(file_path).stem
                        # Return the file name (e.g., 'routes', 'playwrite_service', etc.)
                        return module_file
                    except (ValueError, AttributeError):
                        continue
            return "unknown"
        finally:
            del frame

    def _get_log_file_name(self, module_name):
        """Generate log file name from module name."""
        # Clean up module name for file system
        clean_name = module_name.replace("_", "_").lower()
        return f"{clean_name}_log.log"

    def _create_file_handler(self, module_name):
        """Create a file handler for a specific module."""
        log_file = self.logs_dir / self._get_log_file_name(module_name)
        file_handler = RotatingFileHandler(
            str(log_file), maxBytes=5 * 1024 * 1024, backupCount=5  # 5MB
        )
        file_handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(filename)s:%(lineno)d → %(message)s"
            )
        )
        return file_handler

    def get_logger(self):
        """Get logger for the calling module."""
        with self.lock:
            current_module = self._get_calling_module_name()

            # Get or create logger for this module
            if current_module not in self.loggers:
                logger = logging.getLogger(f"Get_Your_Clothing.{current_module}")
                logger.setLevel(logging.DEBUG)

                # Add console handler (if not already added)
                if not any(
                    isinstance(h, logging.StreamHandler) for h in logger.handlers
                ):
                    console_handler = logging.StreamHandler()
                    console_handler.setFormatter(
                        ColorFormatter(
                            "[%(asctime)s] [%(levelname)s] %(filename)s:%(lineno)d → %(message)s"
                        )
                    )
                    logger.addHandler(console_handler)

                # Add file handler for this module
                file_handler = self._create_file_handler(current_module)
                logger.addHandler(file_handler)
                self.file_handlers[current_module] = file_handler

                # Prevent propagation to root logger to avoid duplicate logs
                logger.propagate = False

                self.loggers[current_module] = logger

                # Log transition if moving from another module
                if self.previous_module and self.previous_module != current_module:
                    # Log in previous module's logger
                    if self.previous_module in self.loggers:
                        prev_logger = self.loggers[self.previous_module]
                        prev_logger.info(
                            f"→ Execution has been moved to {current_module}"
                        )

                    # Log in current module's logger
                    logger.info(f"← Execution started from {self.previous_module}")

            # Update previous module only if it's different (to avoid false transitions)
            if current_module != self.previous_module:
                self.previous_module = current_module

            return self.loggers[current_module]

    def log_transition(self, from_module, to_module):
        """Explicitly log a transition between modules."""
        with self.lock:
            if from_module in self.loggers and to_module in self.loggers:
                from_logger = self.loggers[from_module]
                to_logger = self.loggers[to_module]
                from_logger.info(f"→ Execution has been moved to {to_module}")
                to_logger.info(f"← Execution started from {from_module}")


# Global instance
_logger_manager = FileTrackingLogger()


def get_logger():
    """Get logger instance for the calling module."""
    return _logger_manager.get_logger()


def log_transition(from_module, to_module):
    """Explicitly log a transition between modules.

    Usage:
        from app.utils.logger import log_transition
        log_transition('service_file', 'controller_file')
    """
    _logger_manager.log_transition(from_module, to_module)
