#!/usr/bin/env python3

from eessitarball import EessiTarball

import argparse
import boto3
import botocore
import configparser
import github
import logging
import os
import sys

REQUIRED_CONFIG = {
    'secrets': ['aws_secret_access_key', 'aws_access_key_id', 'github_pat'],
    'paths': ['download_dir', 'ingestion_script', 'metadata_file_extension'],
    'aws': ['staging_bucket'],
    'github': ['staging_repo', 'failed_ingestion_issue_body', 'pr_body'],
}


def error(msg, code=1):
    logging.error(msg)
    sys.exit(code)


def find_tarballs(s3, bucket, extension='.tar.gz'):
    tarballs = [
        object['Key']
        for object in s3.list_objects_v2(Bucket=bucket)['Contents']
        if object['Key'].endswith(extension)
    ]
    return tarballs


def parse_config(path):
    config = configparser.ConfigParser()
    try:
        config.read(path)
    except:
        error(f'Unable to read configuration file {path}!')

    for section in REQUIRED_CONFIG.keys():
        if not section in config:
            error(f'Missing section "{section}" in configuration file {path}.')
        for item in REQUIRED_CONFIG[section]:
            if not item in config[section]:
                error(f'Missing configuration item "{item}" in section "{section}" of configuration file {path}.')
    return config


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, help='path to configuration file', default='automated_ingestion.cfg', dest='config')
    parser.add_argument('-l', '--list', help='only list available tarballs', action='store_true', dest='list_only')
    args = parser.parse_args()
    return args


def main():
    logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)
    args = parse_args()
    config = parse_config(args.config)
    # TODO: check configuration: secrets, paths, permissions on dirs, etc
    gh_pat = config['secrets']['github_pat']
    gh = github.Github(gh_pat)
    s3 = boto3.client(
        's3',
        aws_access_key_id=config['secrets']['aws_access_key_id'],
        aws_secret_access_key=config['secrets']['aws_secret_access_key'],
    )

    tarballs = find_tarballs(s3, config['aws']['staging_bucket'])[-1:]
    # tarballs = find_tarballs(s3, config['aws']['staging_bucket'])
    if args.list_only:
        for num, tarball in enumerate(tarballs):
            print(f'{num}: {tarball}')
        sys.exit(0)

    for tarball in tarballs:
        print(tarball)
        tar = EessiTarball(tarball, config, gh, s3)
        tar.run_handler()


if __name__ == '__main__':
    main()
