#!/bin/bash

# Ingest a tarball containing software, a compatibility layer,
# or init scripts to the EESSI CVMFS repository, and generate
# nested catalogs in a separate transaction.
# This script has to be run on a CVMFS publisher node.

# This script assumes that the given tarball is named like:
# eessi-<version>-{compat,init,software}-[additional information]-<timestamp>.tar.gz
# It also assumes, and verifies, that the  name of the top-level directory of the contents of the
# of the tarball matches <version>, and that name of the second level should is either compat, init, or software.

# Only if it passes these checks, the tarball gets ingested to the base dir in the repository specified below.

repo=pilot.eessi-hpc.org
basedir=versions
decompress="gunzip -c"

function echo_green() {
    echo -e "\e[32m$1\e[0m"
}

function echo_red() {
    echo -e "\e[31m$1\e[0m"
}

function echo_yellow() {
    echo -e "\e[33m$1\e[0m"
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
version=$(echo ${tar_file_basename} | cut -d- -f2)
contents_type_dir=$(echo ${tar_file_basename} | cut -d- -f3)
tar_top_level_dir=$(tar tf "${tar_file}" | head -n 1 | cut -d/ -f1)
# Use the 2nd file/dir in the tarball, as the first one may be just "<version>/"
tar_contents_type_dir=$(tar tf "${tar_file}" | head -n 2 | tail -n 1 | cut -d/ -f2)

# Check if the EESSI version number encoded in the filename
# is valid, i.e. matches the format YYYY.DD
if ! echo "${version}" | egrep -q '^20[0-9][0-9]\.(0[0-9]|1[0-2])$'
then
    error "${version} is not a valid EESSI version."
fi

# Check if the version encoded in the filename matches the top-level dir inside the tarball
if [ "${version}" != "${tar_top_level_dir}" ]
then
    error "the version in the filename (${version}) does not match the top-level directory in the tarball (${tar_top_level_dir})."
fi

# Check if the second-level dir in the tarball is compat, software, or init
if [ "${tar_contents_type_dir}" != "compat" ] && [ "${tar_contents_type_dir}" != "software" ] && [ "${tar_contents_type_dir}" != "init" ]
then
    error "the second directory level of the tarball contents should be either compat, software, or init."
fi

# Check if the name of the second-level dir in the tarball matches to what is specified in the filename
if [ "${contents_type_dir}" != "${tar_contents_type_dir}" ]
then
    error "the contents type in the filename (${contents_type_dir}) does not match the contents type in the tarball (${tar_contents_type_dir})."
fi

# If this is a compat layer tarball, we need to check if it's an update, and if so, use a special procedure
if [ "${tar_contents_type_dir}" = "compat" ]
then
    tar_first_file="$(tar tf "${tar_file}" | head -n 1)"
    # Get OS and architecture from path, which should look like: <version>/compat/<os>/<arch>
    compat_os=$(echo "${tar_first_file}" | cut -d / -f 3)
    compat_arch=$(echo "${tar_first_file}" | cut -d / -f 4)
    # Assume that we already had a compat layer in place if there is a startprefix script in the corresponding CVMFS directory
    if [ -f "/cvmfs/${repo}/${basedir}/${version}/compat/${compat_os}/${compat_arch}/startprefix" ];
    then
        echo_yellow "Compatibility layer for version ${version}, OS ${compat_os}, and architecture ${compat_arch} already exists!"
        echo_yellow "Removing the existing layer, and adding the new one from the tarball..."
        cvmfs_server transaction "${repo}"
        rm -rf "/cvmfs/${repo}/${basedir}/${version}/compat/${compat_os}/${compat_arch}/"
        tar -C "/cvmfs/${repo}/${basedir}/" -xzf "${tar_file}"
        cvmfs_server publish -m "update compat layer for ${version}, ${compat_os}, ${compat_arch}" "${repo}"
        ec=$?
        if [ $ec -eq 0]
        then
            echo_green "Successfully ingested the new compatibility layer!"
            # As the publish operation already created new nested catalogs, we can just exit now
            exit 0
        else
            cvmfs_server abort "${repo}"
            error "Error while updating the compatibility layer, transaction aborted."
        fi
    fi
fi

# For other tarballs, just ingest them using the "cvmfs_server ingest" command
echo "Ingesting tarball ${tar_file} to ${repo}..."
${decompress} "${tar_file}" | cvmfs_server ingest -t - -b "${basedir}" "${repo}"
ec=$?
if [ $ec -eq 0 ]
then
    echo_green "${tar_file} has been ingested to ${repo}."
else
    error "${tar_file} could not be ingested to ${repo}."
fi

# Use the .cvmfsdirtab to generate nested catalogs for the ingested tarball
# ("cvmfs_server ingest" doesn't do this automatically)
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
