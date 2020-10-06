FROM centos:centos8

USER root

RUN yum install -y epel-release
RUN yum install -y ansible
RUN yum install -y httpd
#RUN pip3 install ansible

#COPY entrypoint.sh /entrypoint.sh

#ENTRYPOINT ["/entrypoint.sh"]

RUN echo "[cvmfsstratum0servers]" > ${GITHUB_WORKSPACE}/inventory/hosts
RUN echo "127.0.0.1" >> ${GITHUB_WORKSPACE}/inventory/hosts
RUN ansible-galaxy role install -r ${GITHUB_WORKSPACE}/requirements.yml -p ${GITHUB_WORKSPACE}/roles
RUN ansible-playbook --connection=local ${GITHUB_WORKSPACE}/$1

VOLUME [ “/sys/fs/cgroup” ]
CMD ["/usr/sbin/init"]
