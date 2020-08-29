On the host:
```
sudo singularity build --sandbox fuse-overlay fuse-overlay.def
# Make some directory which is shared with the container (/tmp is mounted automatically)
mkdir -p /tmp/overlay/{upper,work}
singularity shell -S /var/run/cvmfs -B /tmp/cvmfs_cache:/var/lib/cvmfs --fusemount "container:cvmfs2 cvmfs-config.eessi-hpc.org /cvmfs/cvmfs-config.eessi-hpc.org" --fusemount "container:cvmfs2 pilot.eessi-hpc.org /cvmfs_ro/pilot.eessi-hpc.org" -f fuse-overlay/
```

Inside the container:
```
fuse-overlayfs -o lowerdir=/cvmfs_ro/pilot.eessi-hpc.org -o upperdir=/tmp/overlay/upper -o workdir=/tmp/overlay/work /cvmfs/pilot.eessi-hpc.org
```

Now you should be able to make files in `/cvmfs/pilot.eessi-hpc.org`, and they will appear in the `upper` directory.


The following would be even nicer (it automatically mounts the overlay, and doesn't need fakeroot stuff), but it gives weird `Operation not permitted` errors, for instance when you do `cd /cvmfs/pilot.eessi-hpc.org/`:
```
singularity shell -S /var/run/cvmfs -B /tmp/cvmfs_cache:/var/lib/cvmfs --fusemount "container:cvmfs2 cvmfs-config.eessi-hpc.org /cvmfs/cvmfs-config.eessi-hpc.org" --fusemount "container:cvmfs2 pilot.eessi-hpc.org /cvmfs_ro/pilot.eessi-hpc.org" --fusemount "container:fuse-overlayfs -o lowerdir=/cvmfs_ro/pilot.eessi-hpc.org -o upperdir=/tmp/overlay/upper -o workdir=/tmp/overlay/work /cvmfs/pilot.eessi-hpc.org" fuse-overlay/
```
