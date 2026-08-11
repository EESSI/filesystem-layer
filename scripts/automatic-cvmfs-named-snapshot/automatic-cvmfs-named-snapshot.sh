#!/bin/bash

# Automatically create a named snapshot for a given CVMFS repository.
# This script has to be run on a CVMFS publisher node.

# This script assumes that the given repository name is valid and exists in the CVMFS repositories.
# It also assumes that the repository is not currently in a transaction and that it has not had a transaction in the past 30 minutes.

# Only if it passes these checks, the script will open a transaction to the given repository and run the cvmfs_server publish command.
# The script will increment the snapshot number by 1 for each new named snapshot.

# Usage: ./automatic-cvmfs-named-snapshot.sh <cvmfs_repo>

# Function to check if the repository is currently in a transaction
function check_transaction() {
    if cvmfs_server transaction | grep -q "${cvmfs_repo}"; then
        echo "Repository ${cvmfs_repo} is currently in a transaction."
        exit 1
    fi
}

# Function to check if the repository has not had a transaction in the past 30 minutes
function check_last_transaction() {
    last_transaction_timestamp=$(cvmfs_server tag -lx ${cvmfs_repo} | awk '{print $5}' | head -n 1)
    current_timestamp=$(date +%s)
    time_diff=$((current_timestamp - last_transaction_timestamp))
    if [ $time_diff -lt 1800 ]; then
        echo "Repository ${cvmfs_repo} has had a transaction in the past 30 minutes."
        exit 1
    fi
}

# Function to open a transaction to the given repository
function open_transaction() {
    cvmfs_server transaction ${cvmfs_repo}
}

# Function to run the cvmfs_server publish command
function run_publish_command() {
    # Get the last snapshot number
    last_snapshot=$(cvmfs_server tag -lx ${cvmfs_repo} | grep "${cvmfs_repo}-rev" | head -n 1 | awk '{print $1}' | sed 's/.*rev//')

    # Increment the snapshot number and keep same number of digits
    new_snapshot=$((10#$last_snapshot + 1))
    new_snapshot=$(printf "%04d" "$new_snapshot")

    # Run the cvmfs_server publish command
    cvmfs_server publish -a "${cvmfs_repo}-rev${new_snapshot}" "${cvmfs_repo}"
}

# Main script
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <cvmfs_repo>"
    exit 1
fi

cvmfs_repo="$1"

# Check if the repository is part of the CVMFS repositories
if ! cvmfs_server list | awk '{print $1}' | grep -qxF "${cvmfs_repo}" ; then
    echo "Repository ${cvmfs_repo} is not a valid CVMFS repository."
    exit 1
fi

# Check if the repository is currently in a transaction
check_transaction

# Check if the repository has not had a transaction in the past 30 minutes
check_last_transaction

# Open a transaction to the given repository
open_transaction

# Run the cvmfs_server publish command
run_publish_command
