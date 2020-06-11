This roles directory contains submodules that point to the repositories of Ansible roles on which the EESSI playbooks depend. 

## cvmfs

The Galaxy Ansible role for installing/configuring CVMFS, which can be found at:
https://github.com/galaxyproject/ansible-cvmfs

We renamed the directory to "cvmfs", so we can use "cvmfs" as the name of this role in our Ansible playbooks.

## geerlingguy.repo-epel

Ansible role for adding the EPEL repository to RHEL/CentOS systems. The source can be found at:
https://github.com/geerlingguy/ansible-role-repo-epel

We renamed the directory to "geerlingguy.repo-epel", as this is also the name used in the Galaxy CVMFS examples.
