#!/bin/bash -l

cat << EOF > inventory/hosts
[cvmfsstratum0servers]
127.0.0.1

[cvmfsstratum1servers]
127.0.0.1

[cvmfslocalproxies]
127.0.0.1

[cvmfsclients]
127.0.0.1
EOF

ansible-galaxy role install -r requirements.yml -p ./roles
ansible-playbook --connection=local -v $1
