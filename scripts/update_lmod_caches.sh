#!/bin/bash

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

# Check if a stack base dir has been specified
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    error "usage: $0 <path to main directory of an EESSI stack>"
fi

stack_base_dir="$1"
update_lmod_system_cache_files="$2"

# Check if the given stack base dir exists
if [ ! -d ${stack_base_dir} ]
then
  error "${stack_base_dir} does not point to an existing directory!"
fi

# If no Lmod cache update script was specified, try to find one in the compatibility layer of the given stack
if [ -z ${update_lmod_system_cache_files} ]; then
  update_lmod_system_cache_files="${stack_base_dir}/compat/linux/$(uname -m)/usr/share/Lmod/libexec/update_lmod_system_cache_files"
fi
# Make sure that the expected Lmod cache update script exists
if [ ! -f ${update_lmod_system_cache_files} ]
then
  error "expected to find Lmod's cache update script at ${update_lmod_system_cache_files}, but it doesn't exist."
fi

# Find all subtrees of supported CPU targets by looking for "modules" directories, and taking their parent directory
architectures=$(find ${stack_base_dir}/software/ -maxdepth 5 -type d -name modules -exec dirname {} \;)

# Create/update the Lmod cache for all CPU targets
for archdir in ${architectures}
do
  lmod_cache_dir="${archdir}/.lmod/cache"
  modulepath="${archdir}/modules/all"
  # Find any accelerator targets for this CPU, and add them to the module path, so they will be included in the cache
  if [ -d "${archdir}/accel" ]; then
    accelerators=$(find ${archdir}/accel -maxdepth 3 -type d -name modules -exec dirname {} \;)
    for acceldir in ${accelerators}; do
      modulepath="${acceldir}/modules/all:$modulepath"
    done
  fi

  ${update_lmod_system_cache_files} -d ${lmod_cache_dir} -t ${lmod_cache_dir}/timestamp "${modulepath}"
  exit_code=$?
  if [[ ${exit_code} -eq 0 ]]; then
      echo_green "Updated the Lmod cache for ${archdir} using MODULEPATH: ${modulepath}."
      ls -lrt ${lmod_cache_dir}
  else
      echo_red "Updating the Lmod cache failed for ${archdir} using MODULEPATH: ${modulepath}."
      exit ${exit_code}
  fi
done
