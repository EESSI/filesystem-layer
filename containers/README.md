# Containers
This directory contains several Dockerfiles and Singularity definition files for different components,
e.g. CVMFS clients and Squid proxies.

## EESSI-squid-proxy.def: Singularity definition file for Squid proxy

This definition file allows you to build a Singularity container that can be used for running a Squid proxy.

### Build
You can build the container using:
```
sudo singularity build EESSI-squid-proxy.sif EESSI-squid-proxy.def
```
### Configure
Make some directories on the host for storing the cache, logs, and PID file:
```
mkdir -p /tmp/$USER/{var-log-squid,var-run,var-spool-squid,home}
```

Prepare a Squid configuration file, for instance based on our [Ansible template file](https://github.com/EESSI/filesystem-layer/blob/master/templates/eessi_localproxy_squid.conf.j2). Make sure that the ACLs and port number are configured correctly.

Set the following environment variables to the correct local directories and configuration file:
```
export SINGULARITY_BIND="eessi_localproxy_squid.conf:/etc/squid/squid.conf,/tmp/$USER/var-run:/var/run,/tmp/$USER/var-log-squid:/var/log/squid,/tmp/$USER/var-spool-squid:/var/spool/squid"
export SINGULARITY_HOME="/tmp/$USER/home:/home/$USER"
```

### Run

Now start the container as a Singularity instance (which will run it like a service in the background):
```
singularity instance start EESSI-squid-proxy.sif cvmfs_proxy
```

The last argument defines the name for this instance, which can be used to connect a shell (`singularity shell instance://cvmfs_proxy`) or stop the instance:
```
singularity instance stop cvmfs_proxy
```

If you want to interactively start the proxy, you can still do this using:
```
singularity run EESSI-squid-proxy.sif
```
