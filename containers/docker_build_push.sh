#!/bin/bash

os="centos7"
cpu_arch=$(uname -m)
tag="eessi/client-pilot:${os}-${cpu_arch}"

docker build --no-cache -f Dockerfile.EESSI-client-pilot-${os}-${cpu_arch} -t ${tag} .

docker push ${tag}
