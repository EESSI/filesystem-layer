#!/bin/bash

# Ingest a tarball containing software, a compatibility layer,
# or (init) scripts to the EESSI CVMFS repository, and generate
# nested catalogs in a separate transaction.
# This script has to be run on a CVMFS publisher node.

# This script assumes that the given tarball is named like:
# eessi-<version>-{compat,init,scripts,software}-[additional information]-<timestamp>.tar.{gz,zst}
# It also assumes, and verifies, that the  name of the top-level directory of the contents of the
# of the tarball matches <version>, and that name of the second level should is either compat, init, scripts, or software.

# Only if it passes these checks, the tarball gets ingested to the base dir in the repository specified below.

CVMFS_ROOT=${CUSTOM_CVMFS_ROOT:-/cvmfs}

basedir=versions
decompress="gunzip -c"
cvmfs_server="cvmfs_server"
# list of supported architectures for compat and software layers
declare -A archs=(["aarch64"]= ["ppc64le"]= ["riscv64"]= ["x86_64"]=)
# list of supported operating systems for compat and software layers
declare -A oss=(["linux"]= ["macos"]=)
# list of supported tarball content types
declare -A content_types=(["compat"]= ["init"]= ["scripts"]= ["software"]=)


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

function is_repo_owner() {
    if [ -f "/etc/cvmfs/repositories.d/${cvmfs_repo}/server.conf" ]
    then
        . "/etc/cvmfs/repositories.d/${cvmfs_repo}/server.conf"
        [ x"$(whoami)" = x"$CVMFS_USER" ]
    fi
}

function check_repo_vars() {
    if [ -z "${cvmfs_repo}" ]
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
    # is valid, i.e. matches the format YYYY.MM or YYYYMMDD
    if ! echo "${version}" | egrep '(^20[0-9][0-9]\.(0[0-9]|1[0-2])$)|(^20[0-9][0-9][0-9][0-9][0-9][0-9]$)'
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

    # Check if the second-level dir in the tarball is compat, software, scripts or init
    if [ ! -v content_types[${tar_contents_type_dir}] ]
    then
        error "the second directory level of the tarball contents should be either compat, software, scripts or init."
    fi
}

function cvmfs_regenerate_nested_catalogs() {
    # Use the .cvmfsdirtab to generate nested catalogs for the ingested tarball
    echo "Generating the nested catalogs..."
    ${cvmfs_server} transaction "${cvmfs_repo}"
    ${cvmfs_server} publish -m "Generate catalogs after ingesting ${tar_file_basename}" "${cvmfs_repo}"
    ec=$?
    if [ $ec -eq 0 ]
    then
        echo_green "Nested catalogs for ${cvmfs_repo} have been created!"
    else
        echo_red "failure when creating nested catalogs for ${cvmfs_repo}."
    fi
}

function cvmfs_ingest_tarball() {
    # Do a regular "cvmfs_server ingest" for a given tarball,
    # followed by regenerating the nested catalog
    echo "Ingesting tarball ${tar_file} to ${cvmfs_repo}..."
    ${decompress} "${tar_file}" | ${cvmfs_server} ingest -t - -b "${basedir}" "${cvmfs_repo}"
    ec=$?
    if [ $ec -eq 0 ]
    then
        echo_green "${tar_file} has been ingested to ${cvmfs_repo}."
    else
        error "${tar_file} could not be ingested to ${cvmfs_repo}."
    fi

    # "cvmfs_server ingest" doesn't automatically rebuild the nested catalogs,
    # so we do that forcefully by doing an empty transaction
    cvmfs_regenerate_nested_catalogs
}

function check_os() {
    # Check if the operating system directory is correctly set for the contents of the tarball
    os=$(echo "${tar_first_file}" | cut -d / -f $(( $tar_contents_start_level + 1 )))
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
    arch=$(echo "${tar_first_file}" | cut -d / -f $(( $tar_contents_start_level + 2 )))
    if [ -z "${arch}" ]
    then
        error "no architecture directory found in the tarball!"
    fi
    if [ ! -v archs[${arch}] ]
    then
        error "the architecture directory in the tarball is ${arch}, which is not a valid architecture!"
    fi
}

function update_lmod_caches() {
    # Update the Lmod caches for the stacks of all supported CPUs
    script_dir=$(dirname $(realpath $BASH_SOURCE))
    update_caches_script=${script_dir}/update_lmod_caches.sh
    if [ ! -f ${update_caches_script} ]
    then
        error "cannot find the script for updating the Lmod caches; it should be placed in the same directory as the ingestion script!"
    fi
    if [ ! -x ${update_caches_script} ]
    then
        error "the script for updating the Lmod caches (${update_caches_script}) does not have execute permissions!"
    fi
    ${cvmfs_server} transaction "${cvmfs_repo}"
    ${update_caches_script} "${CVMFS_ROOT}/${cvmfs_repo}/${basedir}/${version}"
    ec=$?
    if [ $ec -eq 0 ]; then
        ${cvmfs_server} publish -m "update Lmod caches after ingesting ${tar_file_basename}" "${cvmfs_repo}"
    else
        ${cvmfs_server} abort -f "${cvmfs_repo}"
        error "Update of Lmod caches after ingesting ${tar_file_basename} for ${cvmfs_repo} failed!"
    fi
}

function ingest_init_tarball() {
    # Handle the ingestion of tarballs containing init scripts
    cvmfs_ingest_tarball
}

function ingest_scripts_tarball() {
    # Handle the ingestion of tarballs containing scripts directory with e.g. bash utils and GPU related scripts
    cvmfs_ingest_tarball
}

function ingest_software_tarball() {
    # Handle the ingestion of tarballs containing software installations
    check_arch
    check_os
    cvmfs_ingest_tarball
    if [ "${cvmfs_repo}" = "software.eessi.io" ]; then
        update_lmod_caches
    fi
}

function ingest_compat_tarball() {
    # Handle the ingestion of tarballs containing a compatibility layer
    check_arch
    check_os
    compat_layer_path="${CVMFS_ROOT}/${cvmfs_repo}/${basedir}/${version}/compat/${os}/${arch}"
    # Assume that we already had a compat layer in place if there is a startprefix script in the corresponding CVMFS directory
    if [ -f "${compat_layer_path}/startprefix" ];
    then
        echo_yellow "Compatibility layer for version ${version}, OS ${os}, and architecture ${arch} already exists!"
        ${cvmfs_server} transaction "${cvmfs_repo}"
        # hide the last dir in the path by prepending it with a dot
        hidden_compat_layer_path="$(dirname ${compat_layer_path})/.$(basename ${compat_layer_path})"
        last_suffix=$((ls -1d ${hidden_compat_layer_path}-* | tail -n 1 | xargs basename | cut -d- -f2) 2> /dev/null)
        new_suffix=$(printf '%03d\n' $((${last_suffix:-0} + 1)))
        old_layer_hidden_suffixed_path="${hidden_compat_layer_path}-${new_suffix}"
        echo_yellow "Moving the existing compat layer from ${compat_layer_path} to ${old_layer_hidden_suffixed_path}..."
        mv ${compat_layer_path} ${old_layer_hidden_suffixed_path}
        tar -C "${CVMFS_ROOT}/${cvmfs_repo}/${basedir}/" -xzf "${tar_file}"
        ${cvmfs_server} publish -m "updated compat layer for ${version}, ${os}, ${arch}" "${cvmfs_repo}"
        ec=$?
        if [ $ec -eq 0 ]
        then
            echo_green "Successfully ingested the new compatibility layer!"
        else
            ${cvmfs_server} abort "${cvmfs_repo}"
            error "error while updating the compatibility layer, transaction aborted."
        fi
    else
        cvmfs_ingest_tarball
    fi

}


# Check if a tarball has been specified
if [ "$#" -ne 2 ]; then
    error "usage: $0 <CVMFS repository name> <tarball compressed with gzip or zstd>"
fi

cvmfs_repo="$1"
tar_file="$2"

# Check if the CVMFS repository exists
if ( ! cvmfs_server list | grep -q "${cvmfs_repo}" ); then
    error "CVMFS repository ${cvmfs_repo} does not exist!"
fi

# Check if the given tarball exists
if [ ! -f "${tar_file}" ]; then
    error "tar file ${tar_file} does not exist!"
fi

# Check which compression method is used for the tarball
tar_file_ext="${tar_file##*.}"
if [ "${tar_file_ext}" = "tar" ]; then
    error "can only handle compressed tarballs at the moment."
elif [ "${tar_file_ext}" = "gz" ]; then
    decompress="gunzip -c"
    if ( ! command -v gunzip >& /dev/null ); then
        error "gunzip needs to be installed to handle gzip-compressed tarballs."
    fi
elif [ "${tar_file_ext}" = "zst" ]; then
    decompress="zstd -c"
    if ( ! command -v zstd >& /dev/null ); then
        error "zstd needs to be installed to handle zstd-compressed tarballs."
    fi
else
    error "don't know how to handle tarball extension ${tar_file_ext}."
fi

# Get some information about the tarball
tar_file_basename=$(basename "${tar_file}")
version=$(echo "${tar_file_basename}" | cut -d- -f2)
contents_type_dir=$(echo "${tar_file_basename}" | cut -d- -f3)
tar_first_file=$(tar tf "${tar_file}" | head -n 1)
tar_top_level_dir=$(echo "${tar_first_file}" | cut -d/ -f1)
# Handle longer prefix with project name in dev.eessi.io and
# get the right basedir from the tarball name
if [ "${cvmfs_repo}" = "dev.eessi.io" ]; then
    # the project name is the second to last field in the filename (e.g. eessi-2023.06-software-linux-x86_64-amd-zen4-myproject-1744725142.tar.gz)
    project_name=$(echo "${tar_file_basename}" | rev | cut -d- -f2 | rev)
    basedir="${project_name}"/versions
else
    basedir=versions
fi

tar_contents_start_level=2
tar_contents_type_dir=$(tar tf "${tar_file}" | head -n 2 | tail -n 1 | cut -d/ -f${tar_contents_start_level})

# Check if we are running as the CVMFS repo owner, otherwise run cvmfs_server with sudo
is_repo_owner || cvmfs_server="sudo cvmfs_server"

# Do some checks, and ingest the tarball
check_repo_vars
check_version
# Disable the call to check_contents_type, as it does not work for tarballs produced
# by our build bot that only contain init files (as they have "software" in the filename)
# check_contents_type
ingest_${tar_contents_type_dir}_tarball
