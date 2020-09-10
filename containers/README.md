## Squid proxy Singularity container

Build the container using:
```
sudo singularity build EESSI-squid-proxy.sif EESSI-squid-proxy.def
```

Make some directories on the host for storing the cache, logs, and PID file:
```
cd /somewhere
mkdir logs cache run
```

Prepare a Squid configuration file, for instance based on our template:
https://github.com/EESSI/filesystem-layer/blob/master/templates/eessi_localproxy_squid.conf.j2

Run the container interactively:
```
singularity run -B ./log:/var/log/squid -B ./cache:/var/spool/squid -B run:/var/run -B eessi_localproxy_squid.conf:/etc/squid/squid.conf EESSI-squid-proxy.sif
```

Or start it as an instance:
```
singularity instance start -B ./log:/var/log/squid -B ./cache:/var/spool/squid -B run:/var/run -B eessi_localproxy_squid.conf:/etc/squid/squid.conf EESSI-squid-proxy.sif cvmfs_proxy
```

The last argument defines the name for this instance, which can be used to connect a shell (`singularity shell instance://cvmfs_proxy`) or stop the instance:
```
singularity instance stop cvmfs_proxy
```
