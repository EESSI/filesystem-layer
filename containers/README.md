# Containers for EESSI

This directory contains recipes for containers that are useful in the scope of the EESSI project.

## Client container

Container to provide easy access to EESSI pilot repository,
see https://hub.docker.com/repository/docker/eessi/client-pilot and https://eessi.github.io/docs/pilot.

### Build container + push to Docker Hub

Note: the `docker push` part of the script assumes your Docker Hub creditionals are known
(can be done via `docker login docker.io`, for example).

```shell
./docker_build_push.sh
```
This will build the container for the architecture of your host (e.g. `x86_64` or `aarch64`), and push the image to Docker Hub.

### Run (using Singularity)

```
mkdir -p /tmp/$USER/{var-lib-cvmfs,var-run-cvmfs,home}
export SINGULARITY_BIND="/tmp/$USER/var-run-cvmfs:/var/run/cvmfs,/tmp/$USER/var-lib-cvmfs:/var/lib/cvmfs"
export SINGULARITY_HOME="/tmp/$USER/home:/home/$USER"
export EESSI_CONFIG="container:cvmfs2 cvmfs-config.eessi-hpc.org /cvmfs/cvmfs-config.eessi-hpc.org"
export EESSI_PILOT="container:cvmfs2 pilot.eessi-hpc.org /cvmfs/pilot.eessi-hpc.org"
singularity shell --fusemount "$EESSI_CONFIG" --fusemount "$EESSI_PILOT" docker://eessi/client-pilot:centos7-$(uname -m)
```
