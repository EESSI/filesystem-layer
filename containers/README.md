# Containers for EESSI

This directory contains recipes for containers that are useful in the scope of the EESSI project.

## Client container

Container to provide easy access to EESSI pilot repository,
see https://github.com/users/EESSI/packages/container/package/client-pilot and https://eessi.github.io/docs/pilot.
This container image gets automatically built and pushed to the GitHub Container Registry when one of its
source files (the Dockerfile or the script that generates the CernVM-FS RPMs) gets changed,
or when a new version of the filesystem-layer repository is released.

### Run (using Singularity)

```
mkdir -p /tmp/$USER/{var-lib-cvmfs,var-run-cvmfs,home}
export SINGULARITY_BIND="/tmp/$USER/var-run-cvmfs:/var/run/cvmfs,/tmp/$USER/var-lib-cvmfs:/var/lib/cvmfs"
export SINGULARITY_HOME="/tmp/$USER/home:/home/$USER"
export EESSI_PILOT="container:cvmfs2 pilot.eessi-hpc.org /cvmfs/pilot.eessi-hpc.org"
singularity shell --fusemount "$EESSI_PILOT" docker://ghcr.io/EESSI/client-pilot:centos7
```
