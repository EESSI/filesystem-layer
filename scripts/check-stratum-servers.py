#!/usr/bin/env python3

import argparse
import datetime
import re
import sys
import urllib.error
import urllib.request
import yaml

# Default location for EESSI's Ansible group vars file containing the CVMFS settings.
DEFAULT_ANSIBLE_GROUP_VARS_LOCATION = 'https://raw.githubusercontent.com/EESSI/filesystem-layer/main/inventory/group_vars/all.yml'
# Default fully qualified CVMFS repository name
DEFAULT_CVMFS_FQRN = 'pilot.eessi-hpc.org'
# Maximum amount of time (in minutes) that a Stratum 1 is allowed to not having performed a snapshot.
DEFAULT_MAX_SNAPSHOT_DELAY = 30
# Maximum amount of time (in minutes) allowed between the snapshots of any two Stratum 1 servers.
DEFAULT_MAX_SNAPSHOT_DIFF = 30
# Filename of the last snapshot timestamp.
LAST_SNAPSHOT_FILE = '.cvmfs_last_snapshot'
# Filename of repository manifest.
REPO_MANIFEST_FILE = '.cvmfspublished'


def error(msg):
    """Print an error message to stderr and exit."""
    print(msg, file=sys.stderr)
    sys.exit(1)


def find_stratum_urls(vars_file, fqrn):
    """Find all Stratum 0/1 URLs in a given Ansible YAML vars file that contains the EESSI CVMFS configuration."""
    try:
        group_vars = urllib.request.urlopen(vars_file)
    except:
        error(f'Cannot read the file that contains the Stratum 1 URLs from {vars_file}!')
    try:
        group_vars_yaml = yaml.safe_load(group_vars)
        s1_urls = group_vars_yaml['eessi_cvmfs_server_urls'][0]['urls']
        for repo in group_vars_yaml['eessi_cvmfs_repositories']:
            if repo['repository'] == fqrn:
                s0_url = 'http://' + repo['stratum0'] + '/cvmfs/@fqrn@'
                break
        else:
            error(f'Could not find Stratum 0 URL in {vars_file}!')
    except:
        error(f'Cannot parse the yaml file from {vars_file}!')
    return s0_url, s1_urls


def check_revisions(stratum_urls, fqrn):
    """Check if the Stratum servers are serving the same revision of the repository."""
    errors = []
    revisions = {}
    for stratum in stratum_urls:
        # Get a URL for the CVMFS manifest file.
        manifest_file = stratum.replace('@fqrn@', fqrn) + '/' + REPO_MANIFEST_FILE
        try:
            manifest = urllib.request.urlopen(manifest_file).read()
            # Find the revision number.
            rev_matches = re.findall(rb'\nS([0-9]+)\n', manifest)
            if rev_matches:
                revisions[stratum] = int(rev_matches[0])
            else:
                errors.append(f'Could not find revision number for stratum {stratum}!')
        except urllib.error.HTTPError as e:
            errors.append(f'Could not connect to {stratum}!')

    # Check if all revisions are the same.
    if revisions:
        max_rev = max(revisions.values())
        for stratum, rev in revisions.items():
            if rev < max_rev:
                errors.append(
                    f'Stratum {stratum} is serving an older revision. Maybe it is still completing a snapshot?')

    return errors


def check_snapshots(s1_urls, fqrn, max_snapshot_delay=DEFAULT_MAX_SNAPSHOT_DELAY,
                    max_snapshot_diff=DEFAULT_MAX_SNAPSHOT_DIFF):
    """Check if all the Stratum 1 servers have recently done their last snapshot."""
    errors = []
    last_snapshots = {}
    now = datetime.datetime.utcnow()
    for s1 in s1_urls:
        # Get a URL for the CVMFS last snapshot json file.
        s1_snapshot_file = s1.replace('@fqrn@', fqrn) + '/' + LAST_SNAPSHOT_FILE
        try:
            last_snapshot = urllib.request.urlopen(s1_snapshot_file).read().strip().decode('UTF-8')
            # Parse the timestamp in the json file.
            last_snapshot_time = datetime.datetime.strptime(last_snapshot, "%a %b %d %H:%M:%S %Z %Y")
            last_snapshots[s1] = last_snapshot_time
            # Stratum 1 servers are supposed to make a snapshot every few minutes,
            # so let's check if it is not too far behind.
            if now - last_snapshot_time > datetime.timedelta(minutes=max_snapshot_delay):
                errors.append(
                    f'Stratum 1 {s1} has made its last snapshot {(now - last_snapshot_time).seconds / 60:.0f} minutes ago!')
        except urllib.error.HTTPError as e:
            errors.append(f'Could not connect to {s1_json}!')

    if last_snapshots:
        # Get the Stratum 1 with the most recent snapshot...
        max_snapshot = max(last_snapshots, key=last_snapshots.get)
        # And the one with the oldest snapshot...
        min_snapshot = min(last_snapshots, key=last_snapshots.get)
        # The difference between them should not be too large.
        if last_snapshots[max_snapshot] - last_snapshots[min_snapshot] > datetime.timedelta(minutes=max_snapshot_diff):
            errors.append(
                f'Time difference between last snapshots of {max_snapshot} and {min_snapshot} exceeds the threshold!')

    return errors


def parse_args():
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-v', '--vars', type=str,
        help='URI to the Ansible group vars file that contains the EESSI CVMFS configuration (file:// or http[s]://)',
        default=DEFAULT_ANSIBLE_GROUP_VARS_LOCATION,
        dest='vars_file'
    )
    parser.add_argument(
        '-r', '--fqrn', default=DEFAULT_CVMFS_FQRN, dest='fqrn',
        help='fully qualified CVMFS repository name'
    )
    parser.add_argument(
        '-0', '--s0', action='store_true', dest='s0',
        help='also check the Stratum 0 (make sure that the firewall allows this!)'
    )
    args = parser.parse_args()
    return args


def main():
    """Main function."""
    args = parse_args()
    s0_url, s1_urls = find_stratum_urls(args.vars_file, args.fqrn)
    errors = []
    errors.extend(check_snapshots(s1_urls, args.fqrn))
    errors.extend(check_revisions([s0_url] + s1_urls if args.s0 else s1_urls, args.fqrn))
    if errors:
        error('\n'.join(errors))
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
