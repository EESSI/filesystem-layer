FROM centos:centos7

USER root

RUN yum install -y python3-pip python2-yum
RUN pip3 install ansible

COPY entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
