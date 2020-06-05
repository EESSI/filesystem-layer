![Ansible Lint](https://github.com/bedroge/cvmfs-layer/workflows/Ansible%20Lint/badge.svg)
# CVMFS layer

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

For the installation of all components we make use of the Ansible files provided by the Galaxy project:
https://github.com/galaxyproject/ansible-cvmfs
This repository is added as a submodule inside the roles directory, so make sure to use the --recursive options when cloning this repository:
```
git clone --recursive git@github.com:EESSI/cvmfs-layer.git
```
Alternatively, clone this repository first, and init and update the required submodule later:
```
git clone git@github.com:EESSI/cvmfs-layer.git
cd cvmfs-layer/roles/cvmfs/
git submodule init
git submodule update
```
For more information about (working with) submodules, see:
https://git-scm.com/book/en/v2/Git-Tools-Submodules

You will also need Ansible, which can be easily installed via the package manager of most Linux distributions or via pip. For more details, see the Ansible installation guide:
https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html

### Configuration

The EESSI specific settings can be found in group_vars/all.yml, and in templates we added a template for a Squid configation for the local proxy servers; this file is not included in the Galaxy repository. For all playbooks you will also need to have an appropriate Ansible hosts file; see the supplied hosts.example for the structure and host groups that you need for these playbooks.

## Running the playbooks

In general, all the playbooks can be run like this:
```
ansible-playbook -i hosts -b <name of playbook>.yml
```
where -i allows you to specify the pah to your hosts file, and -b means become, i.e. run with sudo. If this requires a password, include -K, which will ask for the sudo password when running the playbook:
```
ansible-playbook -i hosts -b -K <name of playbook>.yml
```

Before you run any of the commands below, make sure that you updated the file group_vars/all.yml and include the new/extra URLs of any server you want to change/add (e.g. add your Stratum 1).

### Stratum 0
First install the Stratum 0 server:
```
ansible-playbook -i hosts -b -K stratum0.yml
```

Then install the files for the configuration repository:
```
ansible-playbook -i hosts -b -K stratum0-deploy-cvmfs-config.yml
```

### Stratum 1
Installing a Stratum 1 requires a GEO API license key. See here how to obtain it:
https://cvmfs.readthedocs.io/en/stable/cpt-replica.html#geo-api-setup

You can put your license key in group_vars/all.yml, or add a section in your hosts file:
```
[cvmfsstratum1servers:vars]
cvmfs_geo_license_key=XXXXX
```

Install the Stratum 1 using:
```
ansible-playbook -i hosts -b -K stratum1.yml
```
This will automatically make replicas of all the repositories defined in group_vars/all.yml.

### Local proxies
Adjust the template Squid configuration file templates/localproxy_squid.conf.j2, for instance if you want to change the default port or want to limit access. Then run:
```
ansible-playbook -i hosts -b -K localproxy.yml
```

### Clients
Make sure that your hosts file contains the list of hosts where the CVMFS client should be installed. Furthermore, you can add a vars section for the clients that contains the list of (local) proxy servers that your clients should use:
```
[cvmfsclients:vars]
cvmfs_http_proxies=["your-local.proxy:3128"]
```
If you just want to roll out one client without a proxy, you can leave this out.
Finally, run the playbook:
```
ansible-playbook -i hosts -b -K client.yml
```
