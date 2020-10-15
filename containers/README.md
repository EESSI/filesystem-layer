# Containers for EESSI

This directory contains recipes for containers that are useful in the scope of the EESSI project.

## Client container

Container to provide easy access to EESSI pilot repository,
see https://hub.docker.com/repository/docker/eessi/client-pilot and https://eessi.github.io/docs/pilot.

### Build container

```shell
export EESSI_PILOT_VERSION=2020.09
docker build --no-cache -f Dockerfile.EESSI-client-pilot-centos7 -t eessi/client-pilot:centos7-${EESSI_PILOT_VERSION} .
```

### Push to Docker Hub (requires credentials)

```
docker push eessi/client-pilot:centos7-${EESSI_PILOT_VERSION}
```

### Run (using Singularity)

```
mkdir -p /tmp/$USER/{var-lib-cvmfs,var-run-cvmfs,home}
export SINGULARITY_BIND="/tmp/$USER/var-run-cvmfs:/var/run/cvmfs,/tmp/$USER/var-lib-cvmfs:/var/lib/cvmfs"
export SINGULARITY_HOME="/tmp/$USER/home:/home/$USER"
export EESSI_CONFIG="container:cvmfs2 cvmfs-config.eessi-hpc.org /cvmfs/cvmfs-config.eessi-hpc.org"
export EESSI_PILOT="container:cvmfs2 pilot.eessi-hpc.org /cvmfs/pilot.eessi-hpc.org"
singularity shell --fusemount "$EESSI_CONFIG" --fusemount "$EESSI_PILOT" docker://eessi/client-pilot:centos7-${EESSI_PILOT_VERSION}
```
