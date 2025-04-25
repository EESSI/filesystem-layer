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
        endpoint_url=config['aws']['endpoint_url'],
        verify=config['aws']['verify_cert_path'],
    )

    buckets = json.loads(config['aws']['staging_buckets'])
    for bucket, cvmfs_repo in buckets.items():
        if config['github'].get('staging_pr_method', 'individual') == 'grouped':
            # use new grouped PR method
            tarball_groups = find_tarball_groups(s3, bucket, config)
            if args.list_only:
                print(f"#tarball_groups: {len(tarball_groups)}")
                for (repo, pr_id), tarballs in tarball_groups.items():
                    print(f"  {repo}#{pr_id}: #tarballs {len(tarballs)}")
            else:
                for (repo, pr_id), tarballs in tarball_groups.items():
                    if tarballs:
                        # Create a group handler for these tarballs
                        group_handler = EessiTarballGroup(tarballs[0], config, gh_staging_repo, s3, bucket, cvmfs_repo)
                        print(f"group_handler created\n{group_handler.to_string()}")
                        group_handler.process_group(tarballs)
        else:
            # use old individual PR method
            tarballs = find_tarballs(s3, bucket)
            if args.list_only:
                for num, tarball in enumerate(tarballs):
                    print(f'[{bucket}] {num}: {tarball}')
            else:
                for tarball in tarballs:
                    tar = EessiTarball(tarball, config, gh_staging_repo, s3, bucket, cvmfs_repo)
                    tar.run_handler()


if __name__ == '__main__':
    try:
        main()
    except PidFileError:
        error('Another instance of this script is already running!')
