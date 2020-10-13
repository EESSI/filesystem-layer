#!/bin/bash -l

playbook=$1
hostgroup=$(grep hosts $playbook | awk '{print $2}')

# Make an inventory file with just the group for which we are running the playbook.
echo "[$hostgroup]" > inventory/hosts
echo "127.0.0.1" >> inventory/hosts

# Make a site-specific configuration file
touch inventory/local_site_specific_vars.yml
echo 'local_cvmfs_http_proxies_allowed_clients:' >> inventory/local_site_specific_vars.yml
echo '  - 127.0.0.1' >> inventory/local_site_specific_vars.yml

# Don't use the GEO API for the Stratum 1, since we do not have a key here.
export CVMFS_GEO_DB_FILE=NONE

# Only test the cvmfs-config repo on the Stratum 1, as the other ones may be very large.
if [ $playbook == "stratum1.yml" ]
then
  echo 'cvmfs_repositories: "[{{ eessi_cvmfs_config_repo.repository }}]"' >> inventory/local_site_specific_vars.yml
fi

# Install the Ansible dependencies.
ansible-galaxy role install -r requirements.yml -p ./roles

# Print our site-specific configuration file, for debugging purposes.
cat inventory/local_site_specific_vars.yml

# Run the playbook!
ansible-playbook --connection=local -e @inventory/local_site_specific_vars.yml -v ${playbook}
