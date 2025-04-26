#!/usr/bin/env python3

from eessitarball import EessiTarball, EessiTarballGroup
from pid.decorator import pidfile  # noqa: F401
from pid import PidFileError

import argparse
import boto3
import configparser
import github
import json
import logging
import os
import pid
import sys
from pathlib import Path

REQUIRED_CONFIG = {
    'secrets': ['aws_secret_access_key', 'aws_access_key_id', 'github_pat'],
    'paths': ['download_dir', 'ingestion_script', 'metadata_file_extension'],
    'aws': ['staging_buckets'],
    'github': ['staging_repo', 'failed_ingestion_issue_body', 'pr_body'],
}

LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}


def error(msg, code=1):
    """Print an error and exit."""
    logging.error(msg)
    sys.exit(code)


def find_tarballs(s3, bucket, extension='.tar.gz', metadata_extension='.meta.txt'):
    """
    Return a list of all tarballs in an S3 bucket that have a metadata file with
    the given extension (and same filename).
    """
    # TODO: list_objects_v2 only returns up to 1000 objects
    s3_objects = s3.list_objects_v2(Bucket=bucket).get('Contents', [])
    files = [obj['Key'] for obj in s3_objects]

    tarballs = [
        file
        for file in files
        if file.endswith(extension) and file + metadata_extension in files
    ]
    return tarballs


def find_tarball_groups(s3, bucket, config, extension='.tar.gz', metadata_extension='.meta.txt'):
    """Return a dictionary of tarball groups, keyed by (repo, pr_number)."""
    tarballs = find_tarballs(s3, bucket, extension, metadata_extension)
    groups = {}

    for tarball in tarballs:
        # Download metadata to get link2pr info
        metadata_file = tarball + metadata_extension
        local_metadata = os.path.join(config['paths']['download_dir'], os.path.basename(metadata_file))

        try:
            s3.download_file(bucket, metadata_file, local_metadata)
            with open(local_metadata, 'r') as meta:
                metadata = json.load(meta)
                repo = metadata['link2pr']['repo']
                pr = metadata['link2pr']['pr']
                group_key = (repo, pr)

                if group_key not in groups:
                    groups[group_key] = []
                groups[group_key].append(tarball)
        except Exception as err:
            logging.error(f"Failed to process metadata for {tarball}: {err}")
            continue
        finally:
            # Clean up downloaded metadata file
            if os.path.exists(local_metadata):
                os.remove(local_metadata)

    return groups


def parse_config(path):
    """Parse the configuration file."""
    config = configparser.ConfigParser()
    try:
        config.read(path)
    except Exception as err:
        error(f'Unable to read configuration file {path}!\nException: {err}')

    # Check if all required configuration parameters/sections can be found.
    for section in REQUIRED_CONFIG.keys():
        if section not in config:
            error(f'Missing section "{section}" in configuration file {path}.')
        for item in REQUIRED_CONFIG[section]:
            if item not in config[section]:
                error(f'Missing configuration item "{item}" in section "{section}" of configuration file {path}.')

    # Validate staging_pr_method
    staging_method = config['github'].get('staging_pr_method', 'individual')
    if staging_method not in ['individual', 'grouped']:
        error(f'Invalid staging_pr_method: "{staging_method}" in configuration file {path}. Must be either "individual" or "grouped".')

    # Validate PR body templates
    if staging_method == 'individual' and 'individual_pr_body' not in config['github']:
        error(f'Missing "individual_pr_body" in configuration file {path}.')
    if staging_method == 'grouped' and 'grouped_pr_body' not in config['github']:
        error(f'Missing "grouped_pr_body" in configuration file {path}.')

    return config


def parse_args():
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser()

    # Logging options
    logging_group = parser.add_argument_group('Logging options')
    logging_group.add_argument('--log-file',
                             help='Path to log file (overrides config file setting)')
    logging_group.add_argument('--console-level',
                             choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                             help='Logging level for console output (overrides config file setting)')
    logging_group.add_argument('--file-level',
                             choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                             help='Logging level for file output (overrides config file setting)')
    logging_group.add_argument('--quiet',
                             action='store_true',
                             help='Suppress console output (overrides all other console settings)')

    # Existing arguments
    parser.add_argument('-c', '--config', type=str, help='path to configuration file',
                       default='automated_ingestion.cfg', dest='config')
    parser.add_argument('-d', '--debug', help='enable debug mode', action='store_true', dest='debug')
    parser.add_argument('-l', '--list', help='only list available tarballs', action='store_true', dest='list_only')

    return parser.parse_args()


def setup_logging(config, args):
    """
    Configure logging based on configuration file and command line arguments.
    Command line arguments take precedence over config file settings.

    Args:
        config: Configuration dictionary
        args: Parsed command line arguments
    """
    # Get settings from config file
    log_file = config['logging'].get('filename')
    log_format = config['logging'].get('format', '%(levelname)s:%(message)s')
    config_console_level = LOG_LEVELS.get(config['logging'].get('level', 'INFO').upper(), logging.INFO)
    config_file_level = LOG_LEVELS.get(config['logging'].get('file_level', 'DEBUG').upper(), logging.DEBUG)

    # Override with command line arguments if provided
    log_file = args.log_file if args.log_file else log_file
    console_level = getattr(logging, args.console_level) if args.console_level else config_console_level
    file_level = getattr(logging, args.file_level) if args.file_level else config_file_level

    # Debug mode overrides console level
    if args.debug:
        console_level = logging.DEBUG

    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Set root logger to lowest level

    # Create formatters
    console_formatter = logging.Formatter(log_format)
    file_formatter = logging.Formatter('%(asctime)s - ' + log_format)

    # Console handler (only if not quiet)
    if not args.quiet:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # File handler (if log file is specified)
    if log_file:
        # Ensure log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(file_level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


@pid.decorator.pidfile('automated_ingestion.pid')
def main():
    """Main function."""
    args = parse_args()
    config = parse_config(args.config)
    setup_logging(config, args)

    # TODO: check configuration: secrets, paths, permissions on dirs, etc
    gh_pat = config['secrets']['github_pat']
    gh_staging_repo = github.Github(gh_pat).get_repo(config['github']['staging_repo'])
    s3 = boto3.client(
        's3',
        aws_access_key_id=config['secrets']['aws_access_key_id'],
        aws_secret_access_key=config['secrets']['aws_secret_access_key'],
        endpoint_url=config['aws']['endpoint_url'],
        verify=config['aws']['verify_cert_path'],
    )

    buckets = json.loads(config['aws']['staging_buckets'])
    for bucket, cvmfs_repo in buckets.items():
        if config['github'].get('staging_pr_method', 'individual') == 'grouped':
            # use new grouped PR method
            tarball_groups = find_tarball_groups(s3, bucket, config)
            if args.list_only:
                logging.info(f"#tarball_groups: {len(tarball_groups)}")
                for (repo, pr_id), tarballs in tarball_groups.items():
                    logging.info(f"  {repo}#{pr_id}: #tarballs {len(tarballs)}")
            else:
                for (repo, pr_id), tarballs in tarball_groups.items():
                    if tarballs:
                        # Create a group for these tarballs
                        group = EessiTarballGroup(tarballs[0], config, gh_staging_repo, s3, bucket, cvmfs_repo)
                        logging.info(f"group created\n{group.to_string()}")
                        group.process_group(tarballs)
        else:
            # use old individual PR method
            tarballs = find_tarballs(s3, bucket)
            if args.list_only:
                for num, tarball in enumerate(tarballs):
                    logging.info(f'[{bucket}] {num}: {tarball}')
            else:
                for tarball in tarballs:
                    tar = EessiTarball(tarball, config, gh_staging_repo, s3, bucket, cvmfs_repo)
                    tar.run_handler()


if __name__ == '__main__':
    try:
        main()
    except PidFileError:
        error('Another instance of this script is already running!')
