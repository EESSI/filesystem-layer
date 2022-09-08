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
# list of supported architectures for compat and software layers
declare -A archs=(["aarch64"]= ["ppc64le"]= ["riscv64"]= ["x86_64"]=)
# list of supported operating systems for compat and software layers
declare -A oss=(["linux"]= ["macos"]=)
# list of supported tarball content types
declare -A content_types=(["compat"]= ["init"]= ["software"]=)


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

function check_repo_vars() {
    if [ -z "${repo}" ]
    then
        error "the 'repo' variable has to be set to the name of the CVMFS repository."
    fi

    if [ -z "${basedir}" ] || [ "${basedir}" == "/" ]
    then
        error "the 'basedir' variable has to be set to a subdirectory of the CVMFS repository."
    fi
}

function check_version() {
    if [ -z "${version}" ]
    then
        error "EESSI version cannot be derived from the filename."
    fi

    if [ -z "${tar_top_level_dir}" ]
    then
        error "no top level directory can be found in the tarball."
    fi

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
}

function check_contents_type() {
    if [ -z "${contents_type_dir}" ]
    then
        error: "could not derive the content type of the tarball from the filename."
    fi

    if [ -z "${tar_contents_type_dir}" ]
    then
        error: "could not derive the content type of the tarball from the first file in the tarball."
    fi

    # Check if the name of the second-level dir in the tarball matches to what is specified in the filename
    if [ "${contents_type_dir}" != "${tar_contents_type_dir}" ]
    then
        error "the contents type in the filename (${contents_type_dir}) does not match the contents type in the tarball (${tar_contents_type_dir})."
    fi

    # Check if the second-level dir in the tarball is compat, software, or init
    if [ ! -v content_types[${tar_contents_type_dir}] ]
    then
        error "the second directory level of the tarball contents should be either compat, software, or init."
    fi
}

function cvmfs_regenerate_nested_catalogs() {
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
}

function cvmfs_ingest_tarball() {
    # Do a regular "cvmfs_server ingest" for a given tarball,
    # followed by regenerating the nested catalog
    echo "Ingesting tarball ${tar_file} to ${repo}..."
    ${decompress} "${tar_file}" | cvmfs_server ingest -t - -b "${basedir}" "${repo}"
    ec=$?
    if [ $ec -eq 0 ]
    then
        echo_green "${tar_file} has been ingested to ${repo}."
    else
        error "${tar_file} could not be ingested to ${repo}."
    fi

    # "cvmfs_server ingest" doesn't automatically rebuild the nested catalogs,
    # so we do that forcefully by doing an empty transaction
    cvmfs_regenerate_nested_catalogs
}

function check_os() {
    # Check if the operating system directory is correctly set for the contents of the tarball
    os=$(echo "${tar_first_file}" | cut -d / -f 3)
    if [ -z "${os}" ]
    then
        error "no operating system directory found in the tarball!"
    fi
    if [ ! -v oss[${os}] ]
    then
        error "the operating system directory in the tarball is ${os}, which is not a valid operating system!"
    fi
}

function check_arch() {
    # Check if the architecture directory is correctly set for the contents of the tarball
    arch=$(echo "${tar_first_file}" | cut -d / -f 4)
    if [ -z "${arch}" ]
    then
        error "no architecture directory found in the tarball!"
    fi
    if [ ! -v archs[${arch}] ]
    then
        error "the architecture directory in the tarball is ${arch}, which is not a valid architecture!"
    fi
}

function ingest_init_tarball() {
    # Handle the ingestion of tarballs containing init scripts
    cvmfs_ingest_tarball
}

function ingest_software_tarball() {
    # Handle the ingestion of tarballs containing software installations
    check_arch
    check_os
    cvmfs_ingest_tarball
}

function ingest_compat_tarball() {
    # Handle the ingestion of tarballs containing a compatibility layer
    check_arch
    check_os
    # Assume that we already had a compat layer in place if there is a startprefix script in the corresponding CVMFS directory
    if [ -f "/cvmfs/${repo}/${basedir}/${version}/compat/${os}/${arch}/startprefix" ];
    then
        echo_yellow "Compatibility layer for version ${version}, OS ${os}, and architecture ${arch} already exists!"
        echo_yellow "Removing the existing layer, and adding the new one from the tarball..."
        cvmfs_server transaction "${repo}"
        rm -rf "/cvmfs/${repo}/${basedir}/${version}/compat/${os}/${arch}/"
        tar -C "/cvmfs/${repo}/${basedir}/" -xzf "${tar_file}"
        cvmfs_server publish -m "update compat layer for ${version}, ${os}, ${arch}" "${repo}"
        ec=$?
        if [ $ec -eq 0 ]
        then
            echo_green "Successfully ingested the new compatibility layer!"
        else
            cvmfs_server abort "${repo}"
            error "error while updating the compatibility layer, transaction aborted."
        fi
    else
        cvmfs_ingest_tarball
    fi

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

# Get some information about the tarball
tar_file_basename=$(basename "${tar_file}")
version=$(echo "${tar_file_basename}" | cut -d- -f2)
contents_type_dir=$(echo "${tar_file_basename}" | cut -d- -f3)
tar_first_file=$(tar tf "${tar_file}" | head -n 1)
tar_top_level_dir=$(echo "${tar_first_file}" | cut -d/ -f1)
tar_contents_type_dir=$(echo "${tar_first_file}" | head -n 2 | tail -n 1 | cut -d/ -f2)

# Do some checks, and ingest the tarball
check_repo_vars
check_version
check_contents_type
ingest_${tar_contents_type_dir}_tarball
