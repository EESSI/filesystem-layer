![Ansible Lint](https://github.com/EESSI/filesystem-layer/workflows/Ansible%20Lint/badge.svg)
# Filesystem layer

## Introduction
The EESSI project uses the CernVM File System (CVMFS) for distributing its software. More details about CVMFS can be found at its homepage and documentation:

- http://cernvm.cern.ch/portal/filesystem
- https://cvmfs.readthedocs.io

The following introductory video on Youtube gives a quite good overview of CVMFS as well:
https://www.youtube.com/playlist?list=FLqCLabkRddpbHj4wYNFYjAA

## CVMFS infrastructure

The CVMFS layer of the EESSI project consists of the usual CVMFS infrastructure:
* one Stratum 0 server;
* multiple Stratum 1 servers, which contain replicas of the Stratum 0 repositories;
* multiple local Squid proxy servers;
* CVMFS clients with the appropriate configuration files on all the machines that need access to the CVMFS repositories.

## Installation and configuration

### Prerequisites

The main prerequisite is Ansible (https://github.com/ansible/ansible),
which can be easily installed via the package manager of most Linux distributions or via `pip install`.
For more details, see the Ansible installation guide: https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html.

For the installation of all components we make use of two Ansible roles: the CVMFS installation role provided by the Galaxy project (see
https://github.com/galaxyproject/ansible-cvmfs), and a role for adding the EPEL repository (https://github.com/geerlingguy/ansible-role-repo-epel).
Both repositories are added as a submodule inside the `roles` directory, so make sure to use the `--recursive` option when cloning this repository:
```
git clone --recursive https://github.com/EESSI/filesystem-layer.git
```
Alternatively, clone this repository first, and init and update the required submodules later:
```
git clone https://github.com/EESSI/filesystem-layer.git
cd filesystem-layer
git submodule init
git submodule update
```
For more information about (working with) submodules, see:
https://git-scm.com/book/en/v2/Git-Tools-Submodules

### Configuration

The EESSI specific settings can be found in `group_vars/all.yml`, and in `templates` we added our own templates
of Squid configurations for the Stratum 1 and local proxy servers.
For all playbooks you will also need to have an appropriate Ansible `hosts` file;
see the supplied `hosts.example` for the structure and host groups that you need for these playbooks.

## Running the playbooks

In general, all the playbooks can be run like this:
```
ansible-playbook -i hosts -b <name of playbook>.yml
```
where `-i` allows you to specify the path to your hosts file, and `-b` means "become", i.e. run with `sudo`.
If this requires a password, include `-K`, which will ask for the `sudo` password when running the playbook:
```
ansible-playbook -i hosts -b -K <name of playbook>.yml
```

Before you run any of the commands below, make sure that you updated the file `group_vars/all.yml`
and include the new/extra URLs of any server you want to change/add (e.g. add your Stratum 1).

### Firewalls
To make all communication between the CVMFS services possible, some ports have to be opened on the Stratum 0 (default: port 80), 
Stratum 1 (default: port 80 and 8000), and local proxy (default: port 3128).
These default port numbers are listed in `roles/cvmfs/defaults/main.yml`,but can be overridden elsewhere.

The Ansible playbook can update your firewall rules automatically (firewalld on Redhat systems, ufw on Debian systems), 
but by default it will not do this. If you want to enable this functionality, set `cvmfs_manage_firewall` to `true`.
This can be done in either `group_vars/all.yml`, or in a vars section in your hosts or playbook file, or by passing 
`-e cvmfs_manage_firewall=true` to the `ansible-playbook` command.

### Stratum 0
First install the Stratum 0 server:
```
ansible-playbook -i hosts -b -K stratum0.yml
```

Then install the files for the configuration repository:
```
ansible-playbook -i hosts -b -K stratum0-deploy-cvmfs-config.yml
```

Note that there can be only one Stratum 0, so you should only run this playbook
for testing purposes or in case we need to move or redeploy the current Stratum 0 server.

### Stratum 1
Installing a Stratum 1 requires a GEO API license key, which will be used to find
the (geographically) closest Stratum 1 server for your client and proxies.
More information on how to (freely) obtain this key is available in the CVMFS documentation: 
https://cvmfs.readthedocs.io/en/stable/cpt-replica.html#geo-api-setup .

You can put your license key in `group_vars/all.yml`, or add a section in your `hosts` file:
```yaml
[cvmfsstratum1servers:vars]
cvmfs_geo_license_key=XXXXX
```

Furthermore, the Stratum 1 runs a Squid server. The template configuration file can be found at 
`templates/eessi_stratum1_squid.conf.j2`.
If you want to customize it, for instance for limiting the access to the Stratum 1,
you can make your own version of this template file and point to it by editing the playbook or
adding the following to `group_vars/all.yml` or the section in your `hosts` file:
```yaml
cvmfs_squid_conf_src=/path/to/your_stratum1_squid.conf.j2
```
Install the Stratum 1 using:
```
ansible-playbook -i hosts -b -K stratum1.yml
```
This will automatically make replicas of all the repositories defined in `group_vars/all.yml`.

### Local proxies
The local proxies also need a Squid configuration file; the default can be found in 
`templates/localproxy_squid.conf.j2`.

You have to define the lists of IP addresses / ranges (using CIDR notation) that are allowed to use the proxy using the variable `cvmfs_localproxy_allowed_clients`.
You can put this, for instance, in your hosts file. See `hosts.example` for more details.

If you want to customize the Squid configuration more, you can also make your own file, and point to it using `cvmfs_squid_conf_src` (see the Stratum 1 section).

Do keep in mind that you should never accept proxy request from everywhere to everywhere!
Besides having a Squid configuration with the right ACLs, it is recommended to also have a firewall that limits access to your proxy.

Deploy your proxies using:
```
ansible-playbook -i hosts -b -K localproxy.yml
```

### Clients
Make sure that your hosts file contains the list of hosts where the CVMFS client should be installed.
Furthermore, you can add a vars section for the clients that contains the list of (local) proxy servers
that your clients should use:
```yaml
[cvmfsclients:vars]
cvmfs_http_proxies=["your-local.proxy:3128"]
```
If you just want to roll out one client without a proxy, you can leave this out.
Finally, run the playbook:
```
ansible-playbook -i hosts -b -K client.yml
```

## Verification and usage

### Client

Once the client has been installed, you should be able to access all repositories under /cvmfs. They might not immediately show up in that directory before you have actually used them, so you might first have to run ls, e.g.:
```
ls /cvmfs/cvmfs-config.eessi-hpc.org
```

On the client machines you can use the `cvmfs_config` tool for different operations. For instance, you can verify the file system by running:
```
$ sudo cvmfs_config probe cvmfs-config.eessi-hpc.org
Probing /cvmfs/cvmfs-config.eessi-hpc.org... OK
```

Checking for misconfigurations can be done with:
```
sudo cvmfs_config chksetup
```

In case of unclear issues, you can enable the debug mode and log to a file by setting the following environment variable:
```
CVMFS_DEBUGFILE=/some/path/to/cvmfs.log
```

### Proxy / Stratum 1

In order to test your local proxy and/or Stratum 1, even without a client installed, you can use curl:
```
curl --proxy http://url-to-your-proxy:3128 --head http://url-to-your-stratum1/cvmfs/cvmfs-config.eessi-hpc.org/.cvmfspublished
```
This should return:
```
HTTP/1.1 200 OK
...
X-Cache: MISS from url-to-your-proxy
```
The second time you run it, you should get a cache hit:
```
X-Cache: HIT from url-to-your-proxy
```

### Using the CVMFS infrastructure

When the infrastructure seems to work, you can try publishing some new files. This can be done by starting a transaction on the Stratum 0, adding some files, and publishing the transaction:
```
sudo cvmfs_server transaction pilot.eessi-hpc.org
mkdir /cvmfs/pilot.eessi-hpc.org/testdir
touch /cvmfs/pilot.eessi-hpc.org/testdir/testfile
sudo cvmfs_server publish pilot.eessi-hpc.org
```
It might take a few minutes, but then the new file should show up at the clients.
