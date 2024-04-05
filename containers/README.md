# Containers for EESSI

This directory contains recipes for containers that are useful in the scope of the EESSI project.

## Client container

Container to provide easy access to EESSI software stack,
see https://github.com/users/EESSI/packages/container/package/client and https://www.eessi.io/docs/getting_access/eessi_container/.
This container image is based on CentOS 7, and gets automatically built and pushed to the GitHub Container Registry when one of its
source files (the Dockerfile or the script that generates the CernVM-FS RPMs) gets changed,
or when a new version of the filesystem-layer repository is released.

### Run (using Singularity)

```
mkdir -p /tmp/$USER/{var-lib-cvmfs,var-run-cvmfs,home}
export SINGULARITY_BIND="/tmp/$USER/var-run-cvmfs:/var/run/cvmfs,/tmp/$USER/var-lib-cvmfs:/var/lib/cvmfs"
export SINGULARITY_HOME="/tmp/$USER/home:/home/$USER"
export EESSI_STACK="container:cvmfs2 software.eessi.io /cvmfs/software.eessi.io"
singularity shell --fusemount "$EESSI_STACK" docker://ghcr.io/eessi/client:centos7
```

## Build node container

Container that can be used to build and install software to `/cvmfs` by leveraging `fuse-overlayfs` for
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
export EESSI_STACK_READONLY="container:cvmfs2 software.eessi.io /cvmfs_ro/software.eessi.io"
export EESSI_STACK_WRITABLE_OVERLAY="container:fuse-overlayfs -o lowerdir=/cvmfs_ro/software.eessi.io -o upperdir=$EESSI_TMPDIR/overlay-upper -o workdir=$EESSI_TMPDIR/overlay-work /cvmfs/software.eessi.io"
singularity shell --fusemount "$EESSI_STACK_READONLY" --fusemount "$EESSI_STACK_WRITABLE_OVERLAY" docker://ghcr.io/eessi/build-node:debian11
```

For more details about building software, see: https://eessi.github.io/docs/software_layer/build_nodes/
