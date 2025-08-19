#!/bin/bash

# Export a given version of the EESSI stack to a set of tarballs.
# A tarball will be created for each combination of operating system and ISA.
# Each tarball contains the corresponding compatibility layer, the software directories
# for all CPUs of this particular architecture, and additional directories like init and scripts.

repo=pilot.eessi-hpc.org

if [ $# -ne 1 ]; then
    echo "Usage: $0 <EESSI stack version>" >&2
    exit 1
fi

version="$1"
basedir="/cvmfs/${repo}/versions"
oss=$(ls -1 ${basedir}/${version}/compat/)
archs=$(ls -1 ${basedir}/${version}/compat/linux/)

for os in ${oss}
do
  for arch in ${archs}
  do
    tar_contents="${version}/init ${version}/scripts ${version}/compat/${os}/${arch} ${version}/software/${os}/${arch}"
    tar_name="eessi-${version}-${os}-${arch}.tar.gz"
    echo "Creating tarball ${tar_name}..."
    # Run with sudo to prevent permission issues
    sudo tar czf ${tar_name} -C ${basedir} ${tar_contents}
  done
done
