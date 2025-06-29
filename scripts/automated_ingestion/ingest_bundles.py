#!/usr/bin/env python3

from eessi_data_object import EESSIDataAndSignatureObject
from eessi_task import EESSITask
from eessi_task_description import EESSITaskDescription
from eessi_s3_bucket import EESSIS3Bucket
from eessi_logging import error, log_function_entry_exit, log_message, LoggingScope, LOG_LEVELS, set_logging_scopes
from pid.decorator import pidfile  # noqa: F401
from pid import PidFileError

import argparse
import configparser
import github
import json
import logging
import sys
from pathlib import Path
from typing import List

REQUIRED_CONFIG = {
    "secrets": ["aws_secret_access_key", "aws_access_key_id", "github_pat"],
    "paths": ["download_dir", "ingestion_script", "metadata_file_extension"],
    "aws": ["staging_buckets"],
    "github": ["staging_repo", "failed_ingestion_issue_body", "pr_body"],
}


@log_function_entry_exit()
def parse_config(path):
    """Parse the configuration file."""
    config = configparser.ConfigParser()
    try:
        config.read(path)
    except Exception as err:
        error(f"Unable to read configuration file '{path}'!\nException: '{err}'")

    # check if all required configuration parameters/sections can be found
    for section in REQUIRED_CONFIG.keys():
        if section not in config:
            error(f"Missing section '{section}' in configuration file '{path}'.")
        for item in REQUIRED_CONFIG[section]:
            if item not in config[section]:
                error(f"Missing configuration item '{item}' in section '{section}' of configuration file '{path}'.")

    return config


@log_function_entry_exit()
def parse_args():
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser()

    # logging options
    logging_group = parser.add_argument_group("Logging options")
    logging_group.add_argument("--log-file",
                               help="Path to log file (overrides config file setting)")
    logging_group.add_argument("--console-level",
                               choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                               help="Logging level for console output (overrides config file setting)")
    logging_group.add_argument("--file-level",
                               choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                               help="Logging level for file output (overrides config file setting)")
    logging_group.add_argument("--quiet",
                               action="store_true",
                               help="Suppress console output (overrides all other console settings)")
    logging_group.add_argument("--log-scopes",
                               help="Comma-separated list of logging scopes using +/- syntax. "
                               "Examples: '+FUNC_ENTRY_EXIT' (enable only function entry/exit), "
                               "'+ALL,-FUNC_ENTRY_EXIT' (enable all except function entry/exit), "
                               "'+FUNC_ENTRY_EXIT,-EXAMPLE_SCOPE' (enable function entry/exit but disable example)")

    # existing arguments
    parser.add_argument("-c", "--config", type=str, help="path to configuration file",
                        default="ingest_bundles.cfg", dest="config")
    parser.add_argument("-d", "--debug", help="enable debug mode", action="store_true", dest="debug")
    parser.add_argument("-l", "--list", help="only list available tasks", action="store_true", dest="list_only")
    parser.add_argument("--extensions", help="comma-separated list of extensions to process (default: .task)",
                        nargs="?", const=".task", default=False)

    return parser.parse_args()


@log_function_entry_exit()
def setup_logging(config: configparser.ConfigParser, args: argparse.Namespace) -> logging.Logger:
    """
    Configure logging based on configuration file and command line arguments.
    Command line arguments take precedence over config file settings.

    Args:
        config: Configuration parser
        args: Parsed command line arguments

    Returns:
        Logger instance
    """
    # get settings from config file
    log_file = config["logging"].get("log_file")
    config_console_level = LOG_LEVELS.get(config["logging"].get("console_level", "INFO").upper(), logging.INFO)
    config_file_level = LOG_LEVELS.get(config["logging"].get("file_level", "DEBUG").upper(), logging.DEBUG)

    # override with command line arguments if provided
    log_file = args.log_file if args.log_file else log_file
    console_level = getattr(logging, args.console_level) if args.console_level else config_console_level
    file_level = getattr(logging, args.file_level) if args.file_level else config_file_level

    # debug mode overrides console level
    if args.debug:
        console_level = logging.DEBUG

    # set up logging scopes
    if args.log_scopes:
        set_logging_scopes(args.log_scopes)
        log_message(LoggingScope.DEBUG, "DEBUG", "Enabled logging scopes: '%s'", args.log_scopes)

    # create logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # set root logger to lowest level

    # create formatters
    console_formatter = logging.Formatter("%(levelname)-8s: %(message)s")
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)-8s: %(message)s")

    # console handler (only if not quiet)
    if not args.quiet:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # file handler (if log file is specified)
    if log_file:
        # ensure log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(file_level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


@pidfile("shared_lock.pid")  # noqa: F401
@log_function_entry_exit()
def main():
    """Main function."""
    args = parse_args()
    config = parse_config(args.config)
    _ = setup_logging(config, args)  # noqa: F841

    # TODO: check configuration: secrets, paths, permissions on dirs, etc
    extensions = args.extensions.split(",")
    gh_pat = config["secrets"]["github_pat"]
    gh_staging_repo = github.Github(gh_pat).get_repo(config["github"]["staging_repo"])

    buckets = json.loads(config["aws"]["staging_buckets"])
    for bucket, cvmfs_repo in buckets.items():
        # create our custom S3 bucket for this bucket
        s3_bucket = EESSIS3Bucket(config, bucket)

        tasks = find_deployment_tasks(s3_bucket, extensions)
        if args.list_only:
            log_message(LoggingScope.GROUP_OPS, "INFO", "#tasks: %d", len(tasks))
            for num, task in enumerate(tasks):
                log_message(LoggingScope.GROUP_OPS, "INFO", "[%s] %d: '%s'", bucket, num, task)
        else:
            # process each task file
            for task_path in tasks:
                log_message(LoggingScope.GROUP_OPS, "INFO", "Processing task: '%s'", task_path)

                try:
                    # create EESSITask for the task file
                    try:
                        task = EESSITask(
                            EESSITaskDescription(EESSIDataAndSignatureObject(config, task_path, s3_bucket)),
                            config, cvmfs_repo, gh_staging_repo
                        )

                    except Exception as err:
                        log_message(LoggingScope.ERROR, "ERROR", "Failed to create EESSITask for task '%s': '%s'",
                                    task_path, str(err))
                        continue

                    log_message(LoggingScope.GROUP_OPS, "INFO", "Task: %s", task)

#                    previous_state = None
#                    current_state = task.determine_state()
#                    log_message(LoggingScope.GROUP_OPS, "INFO", "Task '%s' is in state '%s'",
#                                task_path, current_state.name)
#                    while (current_state is not None and
#                            current_state != TaskState.DONE and
#                            previous_state != current_state):
#                        previous_state = current_state
#                        log_message(LoggingScope.GROUP_OPS, "INFO",
#                                    "Task '%s': BEFORE handle(): previous state = '%s', current state = '%s'",
#                                    task_path, previous_state.name, current_state.name)
#                        current_state = task.handle()
#                        log_message(LoggingScope.GROUP_OPS, "INFO",
#                                    "Task '%s': AFTER handle(): previous state = '%s', current state = '%s'",
#                                    task_path, previous_state.name, current_state.name)
#
                except Exception as err:
                    log_message(LoggingScope.ERROR, "ERROR", "Failed to process task '%s': '%s'", task_path, str(err))
                    continue


@log_function_entry_exit()
def find_deployment_tasks(s3_bucket: EESSIS3Bucket, extensions: List[str] = None) -> List[str]:
    """
    Return a list of all task files in an S3 bucket with the given extensions,
    but only if a corresponding payload file exists (same name without extension).

    Args:
        s3_bucket: EESSIS3Bucket instance
        extensions: List of file extensions to look for (default: ['.task'])

    Returns:
        List of task filenames found in the bucket that have a corresponding payload
    """
    if extensions is None:
        extensions = [".task"]

    files = []
    continuation_token = None

    while True:
        # list objects with pagination
        if continuation_token:
            response = s3_bucket.list_objects_v2(
                ContinuationToken=continuation_token
            )
        else:
            response = s3_bucket.list_objects_v2()

        # add files from this page
        files.extend([obj["Key"] for obj in response.get("Contents", [])])

        # check if there are more pages
        if response.get("IsTruncated"):
            continuation_token = response.get("NextContinuationToken")
        else:
            break

    # create a set of all files for faster lookup
    file_set = set(files)

    # return only task files that have a corresponding payload
    result = []
    for file in files:
        for ext in extensions:
            if file.endswith(ext) and file[:-len(ext)] in file_set:
                result.append(file)
                break  # found a matching extension, no need to check other extensions

    return result


if __name__ == "__main__":
    try:
        main()
    except PidFileError as err:
        error(f"Another instance of this script is already running! Error: '{err}'")
