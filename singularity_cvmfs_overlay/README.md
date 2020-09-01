On the host:
```
# Build the container
sudo singularity build fuse-overlay.sif fuse-overlay.def
# Make `upper` and `work` directories for the overlay; they should be shared with the container (/tmp is mounted automatically)
mkdir -p /tmp/overlay/{upper,work}
singularity shell -S /var/run/cvmfs -B /tmp/cvmfs_cache:/var/lib/cvmfs --fusemount "container:cvmfs2 cvmfs-config.eessi-hpc.org /cvmfs/cvmfs-config.eessi-hpc.org" --fusemount "container:cvmfs2 pilot.eessi-hpc.org /cvmfs_ro/pilot.eessi-hpc.org" --fusemount "container:fuse-overlayfs -o lowerdir=/cvmfs_ro/pilot.eessi-hpc.org -o upperdir=/tmp/overlay/upper -o workdir=/tmp/overlay/work /cvmfs/pilot.eessi-hpc.org" ./fuse-overlay.sif
```

Now you should be able to make files in `/cvmfs/pilot.eessi-hpc.org`, and they will appear in the `upper` directory.
Note that it currently only seems to work with old versions of fuse-overlayfs (up to 0.4.1).


## Alternative approach

The following method works with newer versions of fuse-overlayfs as well, but does require the -f (fakeroot) option for Singularity. 
For this to work you need user namespaces on the host machine.

On the host:
```
sudo singularity build --sandbox fuse-overlay fuse-overlay.def
singularity shell -S /var/run/cvmfs -B /tmp/cvmfs_cache:/var/lib/cvmfs --fusemount "container:cvmfs2 cvmfs-config.eessi-hpc.org /cvmfs/cvmfs-config.eessi-hpc.org" --fusemount "container:cvmfs2 pilot.eessi-hpc.org /cvmfs_ro/pilot.eessi-hpc.org" -f fuse-overlay/

```
Inside the container:
```
fuse-overlayfs -o lowerdir=/cvmfs_ro/pilot.eessi-hpc.org -o upperdir=/tmp/overlay/upper -o workdir=/tmp/overlay/work /cvmfs/pilot.eessi-hpc.org
```
