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


def read_config(path):
    config = configparser.ConfigParser()
    try:
        config.read(path)
    except:
        error(f'Unable to read configuration file {path}!')
    return config


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, help='path to configuration file', default='automated_ingestion.cfg', dest='config')
    args = parser.parse_args()
    return args


def main():
    # logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)
    args = parse_args()
    config = read_config(args.config)
    gh_pat = config['secrets']['github_pat']
    gh = github.Github(gh_pat)
    s3 = boto3.client(
        's3',
        aws_access_key_id=config['secrets']['aws_access_key_id'],
        aws_secret_access_key=config['secrets']['aws_secret_access_key'],
    )

    # tarballs = find_tarballs()[-3:-2]
    tarballs = find_tarballs(s3, config['aws']['staging_bucket'])[-4:-3]
    # tarballs = find_tarballs()

    for tarball in tarballs:
        print(tarball)
        tar = EessiTarball(tarball, config, gh, s3)
        tar.run_handler()


if __name__ == '__main__':
    main()
