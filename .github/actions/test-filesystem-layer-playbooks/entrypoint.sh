#!/bin/bash -l

cd ${GITHUB_WORKSPACE}

cat << EOF > inventory/hosts
[cvmfsstratum0servers]
127.0.0.1
EOF

ansible-galaxy role install -r requirements.yml -p ./roles
ansible-playbook --connection=local -e ansible_python_interpreter=python3 ${GITHUB_WORKSPACE}/$1
