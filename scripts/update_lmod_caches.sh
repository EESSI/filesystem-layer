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
if [ "$#" -ne 1 ]; then
    error "usage: $0 <path to main directory of an EESSI stack>"
fi

stack_base_dir="$1"

# Check if the given stack base dir exists
if [ ! -d ${stack_base_dir} ]
then
  error "${stack_base_dir} does not point to an existing directory!"
fi

# Check if Lmod's cache update script can be found at the expected location (in the compatibility layer of the gien stack)
update_lmod_system_cache_files="${stack_base_dir}/compat/linux/$(uname -m)/usr/share/Lmod/libexec/update_lmod_system_cache_files"
if [ ! -f ${update_lmod_system_cache_files} ]
then
  error "expected to find Lmod's cache update script at ${update_lmod_system_cache_files}, but it doesn't exist."
fi

# Find all subtrees of supported CPU targets by looking for "modules" directories, and taking their parent directory
architectures=$(find ${stack_base_dir}/software/ -maxdepth 5 -type d -name modules -exec dirname {} \;)

# For every subtree:
# - create an .lmod directory;
# - add an lmodrc.lua file that defines the location of the cache;
# - create or update the cache.
for archdir in ${architectures}
do
  DOT_LMOD="${archdir}/.lmod"
  LMOD_RC="${archdir}/.lmod/lmodrc.lua"

  if [ ! -d "${DOT_LMOD}" ]
  then
    mkdir -p "${DOT_LMOD}/cache"
  fi

  if [ ! -f "${LMOD_RC}" ]
  then
    cat > "${LMOD_RC}" <<LMODRCEOF
propT = {
}
scDescriptT = {
    {
        ["dir"] = "${DOT_LMOD}/cache",
        ["timestamp"] = "${DOT_LMOD}/cache/timestamp",
    },
}
LMODRCEOF
  fi

  ${update_lmod_system_cache_files=} -d ${DOT_LMOD}/cache -t ${DOT_LMOD}/cache/timestamp ${archdir}/modules/all
  echo_green "Updated the Lmod cache for ${archdir}."
done
