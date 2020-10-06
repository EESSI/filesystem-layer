#!/bin/bash -l

cd ${GITHUB_WORKSPACE}

cat << EOF > inventory/hosts
[cvmfsstratum0servers]
127.0.0.1
EOF

#systemctl status httpd
#systemctl start httpd
#systemctl status httpd
echo "systemd" > /proc/1/comm

ansible-galaxy role install -r requirements.yml -p ./roles
ansible-playbook --connection=local -v ${GITHUB_WORKSPACE}/$1
#ansible-playbook --connection=local -e ansible_python_interpreter=python3 ${GITHUB_WORKSPACE}/$1
