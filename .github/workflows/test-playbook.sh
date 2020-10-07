#!/bin/bash -l

playbook=$1
hostgroup=$(grep hosts $playbook | awk '{print $2}')

echo "[$hostgroup]" > inventory/hosts
echo "127.0.0.1" >> inventory/hosts

ansible-galaxy role install -r requirements.yml -p ./roles
ansible-playbook --connection=local -v $1
