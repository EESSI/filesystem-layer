![Ansible Lint](https://github.com/EESSI/filesystem-layer/workflows/Ansible%20Lint/badge.svg)
# Filesystem layer

## Introduction
The EESSI project uses the CernVM File System (CVMFS) for distributing its software. More details about CVMFS can be found at its homepage and documentation:

- http://cernvm.cern.ch/portal/filesystem
- https://cvmfs.readthedocs.io

The following introductory video on Youtube gives a quite good overview of CVMFS as well: https://www.youtube.com/watch?v=MyYx-xaL36k

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
Note that Ansible needs to be able to log in to the remote machines where you want to install some CVMFS component,
and needs to be able to use privilege escalation (e.g. `sudo`) on those machines to execute tasks with root permission.

For the installation of all components we make use of two Ansible roles:
the EESSI CVMFS installation role (see https://github.com/galaxyproject/ansible-cvmfs) 
based on the one developed by the Galaxy project (see https://github.com/galaxyproject/ansible-cvmfs),
and a role for adding the EPEL repository (https://github.com/geerlingguy/ansible-role-repo-epel).

To download the dependency roles do:
```
ansible-galaxy role install -r requirements.yml
```

### Configuration

The EESSI specific settings can be found in `inventory/group_vars/all.yml`, and in `templates` we added our own templates
of Squid configurations for the Stratum 1 and local proxy servers.
For all playbooks you will also need to have an appropriate Ansible `hosts` file in the `inventory` folder;
see the supplied `inventory/hosts.example` for the structure and host groups that you need for these playbooks.

Ansible offers several ways to override any configuration parameters. Of course you can edit a playbook or the `all.yml` file,
but it is best to keep these files unmodified.

#### Machine-specific configuration
If the setting is for one specific machine (e.g. your Stratum 1 machine), it is recommended to make a file in the `inventory/host_vars` directory and use the machine name as name of the file.
This file can contain any settings that should be overridden for this particular machine. See `stratum0host.example` in that directory for an example.
Any other files that you will create in this directory will be ignored by git.


#### Site-specific configuration
Any other site-specific configuration items can go into a file `inventory/local_site_specific_vars.yml` (which will be ignored by git).
We provided an example file that shows the kind of configuration that you should minimally provide.
You can also add more items that you would like to override to this file. See the next section for instructions about passing
your configuration file to the playbook.


## Running the playbooks

In general, all the playbooks can be run like this:
```
ansible-playbook -b -e @inventory/local_site_specific_vars.yml <name of playbook>.yml
```
Here the option `-e @/path/to/your/config.yml` is used to include your site-specific configuration file.
The `-b` option means "become", i.e. run with `sudo`.
If this requires a password, include `-K`, which will ask for the `sudo` password when running the playbook:
```
ansible-playbook -b -K -e @inventory/local_site_specific_vars.yml <name of playbook>.yml
```

Before you run any of the commands below, make sure that you created a `inventory/hosts` file, a site-specific configuration file,
and, if necessary, created machine-specific configuration files in `inventory/host_vars`.

### Firewalls
To make all communication between the CVMFS services possible, some ports have to be opened on the Stratum 0 (default: port 80), 
Stratum 1 (default: port 80 and 8000), and local proxy (default: port 3128).
These default port numbers are listed in the file `defaults/main.yml` of the `ansible-cvmfs` role,
but can be overridden in your local configuration file (`local_site_specific_vars.yml`).

The Ansible playbook can update your firewall rules automatically (`firewalld` on Redhat systems, `ufw` on Debian systems), 
but by default it will not do this. If you want to enable this functionality, set `cvmfs_manage_firewall` to `true`.

### Stratum 0
First install the Stratum 0 server:
```
ansible-playbook -b -K -e @inventory/local_site_specific_vars.yml stratum0.yml
```

Note that there can be only one Stratum 0, so you should only run this playbook
for testing purposes or in case we need to move or redeploy the current Stratum 0 server.

An additional playbook `create_cvmfs_content_structure.yml`, which runs the Ansible role `roles/create_cvmfs_content_structure`,
can be used to automatically deploy certain files and symlinks to the EESSI CVMFS repositories.
The list of files and symlinks can be defined in `roles/create_cvmfs_content_structure/vars`,
where you can add files `<name of the CVMFS repo>.yml`.
A cron job can be used on the Stratum 0 or a publisher node to periodically check for changes in these files, 
and to push updates to your repo.
In order to do this, clone this `filesystem-layer` repository, and let your cron job do a `git pull` followed by
a run of the playbook (e.g. `ansible-playbook --connection=local create_cvmfs_content_structure.yml`).

### Stratum 1
Installing a Stratum 1 requires a GEO API license key, which will be used to find
the (geographically) closest Stratum 1 server for your client and proxies.
More information on how to (freely) obtain this key is available in the CVMFS documentation: 
https://cvmfs.readthedocs.io/en/stable/cpt-replica.html#geo-api-setup .

You can put your license key in the local configuration file `inventory/local_site_specific_vars.yml`. 

Furthermore, the Stratum 1 runs a Squid server. The template configuration file can be found at 
`templates/eessi_stratum1_squid.conf.j2`.
If you want to customize it, for instance for limiting the access to the Stratum 1,
you can make your own version of this template file and point to it by overriding the following setting in `inventory/local_site_specific_vars.yml`.
See the comments in the example file for more details.

Install the Stratum 1 using:
```
ansible-playbook -b -K -e @inventory/local_site_specific_vars.yml stratum1.yml
```
This will automatically make replicas of all the repositories defined in `group_vars/all.yml`.

### Local proxies
The local proxies also need a Squid configuration file; the default can be found in 
`templates/localproxy_squid.conf.j2`.
If you want to customize the Squid configuration more, you can also make your own file, and point to in `inventory/local_site_specific_vars.yml`.
See the comments in the example file for more details.

Furthermore, you have to define the lists of IP addresses / ranges (using CIDR notation) that are allowed to use the proxy using the variable `local_cvmfs_http_proxies_allowed_clients`.
Again, see `inventory/local_site_specific_vars.yml.example` for more details.

Do keep in mind that you should never accept proxy request from everywhere to everywhere!
Besides having a Squid configuration with the right ACLs, it is recommended to also have a firewall that limits access to your proxy.

Deploy your proxies using:
```
ansible-playbook -b -K -e @inventory/local_site_specific_vars.yml localproxy.yml
```

### Clients

#### Method 1: Ansible 
Make sure that your hosts file contains the list of hosts where the CVMFS client should be installed.
Furthermore, you can define a list of (local) proxy servers
that your clients should use in `inventory/local_site_specific_vars.yml` using the parameter `local_cvmfs_http_proxies`.
See `inventory/local_site_specific_vars.yml.example` for more details.
If you just want to roll out one client without a proxy, you can leave this out.

Finally, run the playbook:
```
ansible-playbook -b -K -e @inventory/local_site_specific_vars.yml client.yml
```

#### Method 2: Packages
On many operating systems the CVMFS client can be installed through your package manager.
For details, see the [Getting Started page](https://cvmfs.readthedocs.io/en/stable/cpt-quickstart.html)
in the documentation.

After installing the client, you will have to configure it.
For this you can use the CVMFS configuration packages that we provide for clients.
These packages can be found on the [Releases](https://github.com/eessi/filesystem-layer/releases) page.
Download the package for your operating system, and install it, e.g.:
```
rpm -i cvmfs-config-eessi-*.rpm
dpkg -i cvmfs-config-eessi-*.deb
```

NB! We now also have a yum repository where you can install the configuration package from. If you
opt for this solution you will get automatic updates. Instead of downloading the rpm as above, you
run the following commands:

```
sudo yum -y install http://repo.eessi-infra.org/eessi/rhel/8/noarch/eessi-release-0-1.noarch.rpm
sudo yum check-update
sudo yum -y install cvmfs-config-eessi
```

Next, you need to make a file `/etc/cvmfs/default.local` manually; this file is used for local settings and
contains, for instance, the URL to your local proxy and the size of the local cache. As an example, you can put
the following in this file, which corresponds to not using a proxy and setting the local quota limit to 40000MB:
```
CVMFS_CLIENT_PROFILE=single
CVMFS_QUOTA_LIMIT=40000
```
If you do want to use your own proxy, replace the first line by:
```
CVMFS_HTTP_PROXY=<hostname of your proxy>:<port>
```
For more details about configuring your client, see https://cvmfs.readthedocs.io/en/stable/cpt-configure.html.

Finally, run `cvmfs_config setup` to set up CVMFS.

*Admin note: for building the client configuration packages, see [this section](#building-the-cvmfs-configuration-packages).*

## Verification and usage

### Client

Once the client has been installed, you should be able to access all repositories under `/cvmfs`.
They might not immediately show up in that directory before you have actually used them, so you might first have to run ls, e.g.:
```
ls /cvmfs/software.eessi.io
```

On the client machines you can use the `cvmfs_config` tool for different operations. For instance, you can verify the file system by running:
```
$ sudo cvmfs_config probe software.eessi.io
Probing /cvmfs/software.eessi.io... OK
```

Checking for misconfigurations can be done with:
```
sudo cvmfs_config chksetup
```

In case of unclear issues, you can enable the debug mode and log to a file by setting the following environment variable:
```
CVMFS_DEBUGLOG=/some/path/to/cvmfs.log
```

### Proxy / Stratum 1

In order to test your local proxy and/or Stratum 1, even without a client installed, you can use
curl. Leave out the `--proxy http://url-to-your-proxy:3128` if you do not use a proxy.

```
curl --proxy http://url-to-your-proxy:3128 --head http://url-to-your-stratum1/cvmfs/software.eessi.io/.cvmfspublished
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

Example with an EESSI Stratum 1 server:
```
curl --head http://aws-eu-central-s1.eessi.science/cvmfs/software.eessi.io/.cvmfspublished
```

### Using the CVMFS infrastructure

When the infrastructure seems to work, you can try publishing some new files. This can be done by starting a transaction on the Stratum 0, adding some files, and publishing the transaction:
```
sudo cvmfs_server transaction software.eessi.io
mkdir /cvmfs/software.eessi.io/testdir
touch /cvmfs/software.eessi.io/testdir/testfile
sudo cvmfs_server publish software.eessi.io
```
It might take a few minutes, but then the new file should show up at the clients.


## Building the CVMFS configuration packages

For each push and pull request to the `main` branch, packages are automatically built by a Github Action.
The resulting (unversioned) packages can be found as build artifacts on the page of each run of this action.
When a new tag is created to mark a versioned release of the repository (e.g. `v1.2.3`, where the `v` is required!),
the action builds a package with the same version number, creates a release, and stores the packages
as release assets.

# License

The software in this repository is distributed under the terms of the
[GNU General Public License v2.0](https://opensource.org/licenses/GPL-2.0).

See [LICENSE](https://github.com/EESSI/filesystem-layer/blob/main/LICENSE) for more information.

SPDX-License-Identifier: GPL-2.0-only
