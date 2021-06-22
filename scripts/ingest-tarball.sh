#!/bin/bash

# Ingest a tarball containing software, a compatibility layer,
# or init scripts to the EESSI CVMFS repository, and generate
# nested catalogs in a separate transaction.
# This script has to be run on a CVMFS publisher node.

repo=pilot.eessi-hpc.org
decompress="gunzip -c"

function echo_green() {
    echo -e "\e[32m$1\e[0m"
}

function echo_red() {
    echo -e "\e[31m$1\e[0m"
}

function error() {
    echo_red "ERROR: $1" >&2
    exit 1
}
# Check if a tarball has been specified
if [ "$#" -ne 1 ]; then
    error "usage: $0 <gzipped tarball>"
fi

tar_file="$1"

# Check if the given tarball exists
if [ ! -f "${tar_file}" ]; then
    error "tar file ${tar_file} does not exist!"
fi

tar_file_basename=$(basename "${tar_file}")
version=$(echo ${tar_file} | cut -d- -f2)
top_level_dir=$(echo ${tar_file} | cut -d- -f3)
tar_top_level_dir=$(tar tf "${tar_file}" | head -n 1 | cut -d/ -f1)

# Check if the top level dir encoded in the filename
# matches the top lever dir inside the tarball
if [ "${top_level_dir}" != "${tar_top_level_dir}" ]
then
    error "the top level directory in the filename (${top_level_dir}) does not match the top level directory in the tar ball (${tar_top_level_dir})."
fi

# We assume that the top level dir must be compat, software, or init
if [ "${tar_top_level_dir}" != "compat" ] && [ "${tar_top_level_dir}" != "software" ] && [ "${tar_top_level_dir}" != "init" ]
then
    error "the top level directory in the tar ball should be either compat, software, or init!"
fi

# Check of the EESSI version number encoded in the filename
# is a valid, i.e. matches the format YYYY.DD
if ! echo "${version}" | egrep -q '^20[0-9][0-9]\.(0[0-9]|1[0-2])$'
then
    error "${version} is not a valid EESSI version."
fi

# Ingest the tarball to the repository
echo "Ingesting tarball ${tar_file} to ${repo}..."
${decompress} "${tar_file}" | cvmfs_server ingest -t - -b "${version}" "${repo}"
ec=$?
if [ $ec -eq 0 ]
then
    echo_green "${tar_file} has been ingested to ${repo}."
else
    error "${tar_file} could not be ingested to ${repo}."
fi

# Use the .cvmfsdirtab to generate nested catalogs for the ingested tarball
echo "Generating the nested catalogs..."
cvmfs_server transaction "${repo}"
cvmfs_server publish -m "Generate catalogs after ingesting ${tar_file_basename}" "${repo}"
ec=$?
if [ $ec -eq 0 ]
then
    echo_green "Nested catalogs for ${repo} have been created!"
else
    echo_red "failure when creating nested catalogs for ${repo}."
fi
