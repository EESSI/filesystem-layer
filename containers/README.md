# Containers for EESSI

This directory contains recipes for containers that are useful in the scope of the EESSI project.

## Client container

Container to provide easy access to EESSI pilot repository,
see https://github.com/users/EESSI/packages/container/package/client-pilot and https://eessi.github.io/docs/pilot.
This container image is based on CentOS 7, and gets automatically built and pushed to the GitHub Container Registry when one of its
source files (the Dockerfile or the script that generates the CernVM-FS RPMs) gets changed,
or when a new version of the filesystem-layer repository is released.

### Run (using Singularity)

```
mkdir -p /tmp/$USER/{var-lib-cvmfs,var-run-cvmfs,home}
export SINGULARITY_BIND="/tmp/$USER/var-run-cvmfs:/var/run/cvmfs,/tmp/$USER/var-lib-cvmfs:/var/lib/cvmfs"
export SINGULARITY_HOME="/tmp/$USER/home:/home/$USER"
export EESSI_PILOT="container:cvmfs2 pilot.eessi-hpc.org /cvmfs/pilot.eessi-hpc.org"
singularity shell --fusemount "$EESSI_PILOT" docker://ghcr.io/eessi/client-pilot:centos7
```

## Build node container

Container that can be used to build and install software to /cvmfs by leveraging `fuse-overlayfs` for
providing a writable overlay.
The container image is based on Debian 10.6, and gets automatically built and pushed to the GitHub Container Registry when one of its
source files (the Dockerfile or the script that generates the CernVM-FS deb packages) gets changed,
or when a new version of the filesystem-layer repository is released.

### Run (using Singularity)
```
export EESSI_TMPDIR=/tmp/$USER/EESSI
mkdir -p $EESSI_TMPDIR
mkdir -p $EESSI_TMPDIR/{home,overlay-upper,overlay-work}
mkdir -p $EESSI_TMPDIR/{var-lib-cvmfs,var-run-cvmfs}
export SINGULARITY_CACHEDIR=$EESSI_TMPDIR/singularity_cache
export SINGULARITY_BIND="$EESSI_TMPDIR/var-run-cvmfs:/var/run/cvmfs,$EESSI_TMPDIR/var-lib-cvmfs:/var/lib/cvmfs"
export SINGULARITY_HOME="$EESSI_TMPDIR/home:/home/$USER"
export EESSI_PILOT_READONLY="container:cvmfs2 pilot.eessi-hpc.org /cvmfs_ro/pilot.eessi-hpc.org"
export EESSI_PILOT_WRITABLE_OVERLAY="container:fuse-overlayfs -o lowerdir=/cvmfs_ro/pilot.eessi-hpc.org -o upperdir=$EESSI_TMPDIR/overlay-upper -o workdir=$EESSI_TMPDIR/overlay-work /cvmfs/pilot.eessi-hpc.org"
singularity shell --fusemount "$EESSI_PILOT_READONLY" --fusemount "$EESSI_PILOT_WRITABLE_OVERLAY" docker://ghcr.io/eessi/build-node:debian11
```

For more details about building software, see: https://eessi.github.io/docs/software_layer/build_nodes/
