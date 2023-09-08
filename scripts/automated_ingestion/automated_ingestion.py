#!/usr/bin/env python3

from eessitarball import EessiTarball
from pid.decorator import pidfile
from pid import PidFileError

import argparse
import boto3
import botocore
import configparser
import github
import logging
import os
import pid
import sys

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
    """Return a list of all tarballs in an S3 bucket that have a metadata file with the given extension (and same filename)."""
    # TODO: list_objects_v2 only returns up to 1000 objects
    s3_objects = s3.list_objects_v2(Bucket=bucket).get('Contents', [])
    files = [obj['Key'] for obj in s3_objects]

    tarballs = [
        file
        for file in files
        if file.endswith(extension)
           and file + metadata_extension in files
    ]
    return tarballs


def parse_config(path):
    """Parse the configuration file."""
    config = configparser.ConfigParser()
    try:
        config.read(path)
    except:
        error(f'Unable to read configuration file {path}!')

    # Check if all required configuration parameters/sections can be found.
    for section in REQUIRED_CONFIG.keys():
        if not section in config:
            error(f'Missing section "{section}" in configuration file {path}.')
        for item in REQUIRED_CONFIG[section]:
            if not item in config[section]:
                error(f'Missing configuration item "{item}" in section "{section}" of configuration file {path}.')
    return config


def parse_args():
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, help='path to configuration file',
                        default='automated_ingestion.cfg', dest='config')
    parser.add_argument('-d', '--debug', help='enable debug mode', action='store_true', dest='debug')
    parser.add_argument('-l', '--list', help='only list available tarballs', action='store_true', dest='list_only')
    args = parser.parse_args()
    return args


@pid.decorator.pidfile('automated_ingestion.pid')
def main():
    """Main function."""
    args = parse_args()
    config = parse_config(args.config)
    log_file = config['logging'].get('filename', None)
    log_format = config['logging'].get('format', '%(levelname)s:%(message)s')
    log_level = LOG_LEVELS.get(config['logging'].get('level', 'INFO').upper(), logging.WARN)
    log_level = logging.DEBUG if args.debug else log_level
    logging.basicConfig(filename=log_file, format=log_format, level=log_level)
    # TODO: check configuration: secrets, paths, permissions on dirs, etc
    gh_pat = config['secrets']['github_pat']
    gh_staging_repo = github.Github(gh_pat).get_repo(config['github']['staging_repo'])
    s3 = boto3.client(
        's3',
        aws_access_key_id=config['secrets']['aws_access_key_id'],
        aws_secret_access_key=config['secrets']['aws_secret_access_key'],
    )

    buckets = [x.strip() for x in config['aws']['staging_buckets'].split(',')]
    for bucket in buckets:
        tarballs = find_tarballs(s3, bucket)
        if args.list_only:
            for num, tarball in enumerate(tarballs):
                print(f'[{bucket}] {num}: {tarball}')
        else:
            for tarball in tarballs:
                tar = EessiTarball(tarball, config, gh_staging_repo, s3, bucket)
                tar.run_handler()


if __name__ == '__main__':
    try:
        main()
    except PidFileError:
        error('Another instance of this script is already running!')
