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

The EESSI specific settings can be found in group_vars/all.yml, and in templates we added a template for a Squid configation for the local proxy servers; this file is not included in the Galaxy repository.

In order to run one of these playbooks, you will have to use a hosts file that includes at least the group of nodes for which you are running a playbook. An example of the file that shows the correct structure can be found in hosts.example.
The playbooks can then be run as follows:
```
ansible-playbook -i hosts -b <name of playbook>.yml
```
where -b means become, i.e. run with sudo. If this requires a password, include -K:
```
ansible-playbook -i hosts -b -K <name of playbook>.yml
```
