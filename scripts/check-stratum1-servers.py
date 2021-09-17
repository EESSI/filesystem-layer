#!/usr/bin/env python3

import argparse
import datetime
import sys
import urllib.error
import urllib.request
import yaml

LAST_SNAPSHOT_FILE = '.cvmfs_last_snapshot'


def error(msg):
    """Print an error message to stderr and exit."""
    print(msg, file=sys.stderr)
    sys.exit(1)


def find_stratum1_urls(vars_file):
    """Find all Stratum 1 URLs in a given Ansible YAML vars file that contains the EESSI CVMFS configuration."""
    try:
        group_vars = urllib.request.urlopen(vars_file)
    except:
        error(f'Cannot read the file that contains the Stratum 1 URLs from {vars_file}!')
    try:
        group_vars_yaml = yaml.safe_load(group_vars)
        urls = group_vars_yaml['eessi_cvmfs_server_urls'][0]['urls']
    except:
        error(f'Cannot parse the yaml file from {vars_file}!')
    return urls


def check_out_of_sync(s1_urls, fqrn, max_snapshot_delay=30, max_snapshot_diff=30):
    """Check if all the Stratum 1 servers are in sync."""
    errors = []
    last_snapshots = {}
    now = datetime.datetime.utcnow()
    for s1 in s1_urls:
        # Get a URL for the CVMFS last snapshot json file.
        s1_json = s1.replace('@fqrn@', fqrn) + '/' + LAST_SNAPSHOT_FILE
        try:
            last_snapshot = urllib.request.urlopen(s1_json).read().strip().decode('UTF-8')
            # Parse the timestamp in the json file.
            last_snapshot_time = datetime.datetime.strptime(last_snapshot, "%a %b %d %H:%M:%S %Z %Y")
            last_snapshots[s1]= last_snapshot_time
            # Stratum 1 servers are supposed to make a snapshot every few minutes,
            # so let's check if it is not too far behind.
            if now - last_snapshot_time > datetime.timedelta(minutes=max_snapshot_delay):
                errors.append(f'Stratum 1 {s1} has made its last snapshot {(now - last_snapshot_time).minutes} minutes ago!')
        except urllib.error.HTTPError as e:
            errors.append(f'Could not connect to {s1_json}!')

    if last_snapshots:
        # Get the Stratum 1 with the most recent snapshot...
        max_snapshot = max(last_snapshots, key=last_snapshots.get)
        # And the one with the oldest snapshot...
        min_snapshot = min(last_snapshots, key=last_snapshots.get)
        # The difference between them should not be too large.
        if last_snapshots[max_snapshot] - last_snapshots[min_snapshot] > datetime.timedelta(minutes=max_snapshot_diff):
            errors.append(f'Time difference between last snapshots of {max_snapshot} and {min_snapshot} exceeds the threshold!')
    return errors


def parse_args():
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-v', '--vars', type=str,
        help='URI to the Ansible group vars file that contains the EESSI CVMFS configuration (file:// or http[s]://)',
        default='https://raw.githubusercontent.com/EESSI/filesystem-layer/main/inventory/group_vars/all.yml',
        dest='vars_file'
    )
    parser.add_argument(
        '-r', '--fqrn', help='fully qualified CVMFS repository name', default='pilot.eessi-hpc.org', dest='fqrn'
    )
    args = parser.parse_args()
    return args


def main():
    """Main function."""
    args = parse_args()
    s1_urls = find_stratum1_urls(args.vars_file)
    errors = []
    errors.extend(check_out_of_sync(s1_urls, args.fqrn))
    if errors:
        error('\n'.join(errors))
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
