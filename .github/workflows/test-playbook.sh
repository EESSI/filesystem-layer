#!/bin/bash -l

playbook=$1
hostgroup=$(grep hosts $playbook | awk '{print $2}')

echo "[$hostgroup]" > inventory/hosts
echo "127.0.0.1" >> inventory/hosts

touch inventory/local_site_specific_vars.yml

export CVMFS_GEO_DB_FILE=NONE

if [ $playbook == "stratum1.yml" ]
then
  echo 'cvmfs_repositories: "[{{ eessi_cvmfs_config_repo.repository }}]"' >> inventory/local_site_specific_vars.yml
fi


echo 'local_cvmfs_http_proxies_allowed_clients:' >> inventory/local_site_specific_vars.yml
echo '  - 127.0.0.1' >> inventory/local_site_specific_vars.yml

ansible-galaxy role install -r requirements.yml -p ./roles
ansible-playbook --connection=local -e @inventory/local_site_specific_vars.yml ${playbook}
