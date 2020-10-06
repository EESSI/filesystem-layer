FROM centos:centos8

USER root

RUN yum install -y epel-release
RUN yum install -y ansible
RUN yum install -y httpd
#RUN pip3 install ansible

COPY entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

VOLUME [ “/sys/fs/cgroup” ]
CMD ["/usr/sbin/init"]
