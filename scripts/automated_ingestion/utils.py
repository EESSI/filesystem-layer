import hashlib
import json
import requests
import logging
import functools
import time
import os
import inspect
from enum import IntFlag, auto

class LoggingScope(IntFlag):
    """Enumeration of different logging scopes."""
    NONE = 0
    FUNC_ENTRY_EXIT = auto()  # Function entry/exit logging
    DOWNLOAD = auto()         # Logging related to file downloads
    VERIFICATION = auto()     # Logging related to signature and checksum verification
    STATE_CHANGE = auto()     # Logging related to tarball state changes
    GITHUB_OPS = auto()       # Logging related to GitHub operations (PRs, issues, etc.)
    GROUP_OPS = auto()        # Logging related to tarball group operations
    ERROR = auto()           # Error logging (separate from other scopes for easier filtering)
    DEBUG = auto()           # Debug-level logging (separate from other scopes for easier filtering)
    ALL = (FUNC_ENTRY_EXIT | DOWNLOAD | VERIFICATION | STATE_CHANGE | 
           GITHUB_OPS | GROUP_OPS | ERROR | DEBUG)

# Global setting for logging scopes
ENABLED_LOGGING_SCOPES = LoggingScope.NONE

# Global variable to track call stack depth
_call_stack_depth = 0

def set_logging_scopes(scopes):
    """
    Set the enabled logging scopes.

    Args:
        scopes: Can be:
            - A LoggingScope value
            - A string with comma-separated values using +/- syntax:
              - "+SCOPE" to enable a scope
              - "-SCOPE" to disable a scope
              - "ALL" or "+ALL" to enable all scopes
              - "-ALL" to disable all scopes
              Examples:
                "+FUNC_ENTRY_EXIT"  # Enable only function entry/exit
                "+FUNC_ENTRY_EXIT,-EXAMPLE_SCOPE"  # Enable function entry/exit but disable example
                "+ALL,-FUNC_ENTRY_EXIT"  # Enable all scopes except function entry/exit
    """
    global ENABLED_LOGGING_SCOPES

    if isinstance(scopes, LoggingScope):
        ENABLED_LOGGING_SCOPES = scopes
        return

    if isinstance(scopes, str):
        # Start with no scopes enabled
        ENABLED_LOGGING_SCOPES = LoggingScope.NONE

        # Split into individual scope specifications
        scope_specs = [s.strip() for s in scopes.split(",")]

        for spec in scope_specs:
            if not spec:
                continue

            # Check for ALL special case
            if spec.upper() in ["ALL", "+ALL"]:
                ENABLED_LOGGING_SCOPES = LoggingScope.ALL
                continue
            elif spec.upper() == "-ALL":
                ENABLED_LOGGING_SCOPES = LoggingScope.NONE
                continue

            # Parse scope name and operation
            operation = spec[0]
            scope_name = spec[1:].strip().upper()

            try:
                scope_enum = LoggingScope[scope_name]
                if operation == '+':
                    ENABLED_LOGGING_SCOPES |= scope_enum
                elif operation == '-':
                    ENABLED_LOGGING_SCOPES &= ~scope_enum
                else:
                    logging.warning(f"Invalid operation '{operation}' in scope specification: {spec}")
            except KeyError:
                logging.warning(f"Unknown logging scope: {scope_name}")

    elif isinstance(scopes, list):
        # Convert list to comma-separated string and process
        set_logging_scopes(",".join(scopes))

def is_logging_scope_enabled(scope):
    """Check if a specific logging scope is enabled."""
    return bool(ENABLED_LOGGING_SCOPES & scope)

def send_slack_message(webhook, msg):
    """Send a Slack message."""
    slack_data = {'text': msg}
    response = requests.post(
        webhook, data=json.dumps(slack_data),
        headers={'Content-Type': 'application/json'}
    )
    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )


def sha256sum(path):
    """Calculate the sha256 checksum of a given file."""
    sha256_hash = hashlib.sha256()
    with open(path, 'rb') as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(8192), b''):
            sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


def log_function_entry_exit(logger=None):
    """
    Decorator that logs function entry and exit with timing information.
    Only logs if the FUNC_ENTRY_EXIT scope is enabled.

    Args:
        logger: Optional logger instance. If not provided, uses the module's logger.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            global _call_stack_depth

            if not is_logging_scope_enabled(LoggingScope.FUNC_ENTRY_EXIT):
                return func(*args, **kwargs)

            if logger is None:
                log = logging.getLogger(func.__module__)
            else:
                log = logger

            # Get context information if available
            context = ""
            if len(args) > 0 and hasattr(args[0], 'object'):
                # For EessiTarball methods, show the tarball name and state
                tarball = args[0]
                filename = os.path.basename(tarball.object)

                # Format filename to show important parts
                if len(filename) > 30:
                    parts = filename.split('-')
                    if len(parts) >= 6:  # Ensure we have all required parts
                        # Get version, component, last part of architecture, and epoch
                        version = parts[1]
                        component = parts[2]
                        arch_last = parts[-2].split('-')[-1]  # Last part of architecture
                        epoch = parts[-1]  # includes file extension
                        filename = f"{version}-{component}-{arch_last}-{epoch}"
                    else:
                        # Fallback to simple truncation if format doesn't match
                        filename = f"{filename[:15]}...{filename[-12:]}"

                context = f" [{filename}"
                if hasattr(tarball, 'state'):
                    context += f" in {tarball.state}"
                context += "]"

            # Create indentation based on call stack depth
            indent = "  " * _call_stack_depth

            # Get file name and line number of the decorated function
            frame = inspect.currentframe()
            # Get the frame of the decorated function (one level up from the wrapper)
            func_frame = frame.f_back
            file_name = os.path.basename(func_frame.f_code.co_filename)
            line_no = func_frame.f_lineno

            start_time = time.time()
            log.info(f"{indent}Entering {func.__name__} at {file_name}:{line_no}{context}")
            _call_stack_depth += 1
            try:
                result = func(*args, **kwargs)
                _call_stack_depth -= 1
                end_time = time.time()
                log.info(f"{indent}Leaving {func.__name__} at {file_name}:{line_no}"
                        f"{context} (took {end_time - start_time:.2f}s)")
                return result
            except Exception as err:
                _call_stack_depth -= 1
                end_time = time.time()
                log.info(f"{indent}Leaving {func.__name__} at {file_name}:{line_no}"
                        f"{context} with exception (took {end_time - start_time:.2f}s)")
                raise err
        return wrapper
    return decorator

def log_with_scope(scope, logger=None):
    """
    Decorator that checks if a specific logging scope is enabled before logging.

    Args:
        scope: LoggingScope value indicating which scope this logging belongs to
        logger: Optional logger instance. If not provided, uses the root logger.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not is_logging_scope_enabled(scope):
                return func(*args, **kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator

def log_message(scope, level, msg, *args, logger=None, **kwargs):
    """
    Log a message if the specified scope is enabled.

    Args:
        scope: LoggingScope value indicating which scope this logging belongs to
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        msg: Message to log
        logger: Optional logger instance. If not provided, uses the root logger.
        *args, **kwargs: Additional arguments to pass to the logging function
    """
    if not is_logging_scope_enabled(scope):
        return

    log = logger or logging.getLogger()
    log_func = getattr(log, level.lower())
    log_func(msg, *args, **kwargs)

# Example usage:
# log_message(LoggingScope.DOWNLOAD, 'INFO', "Downloading file: %s", filename)
# log_message(LoggingScope.ERROR, 'ERROR', "Failed to download: %s", error_msg)
