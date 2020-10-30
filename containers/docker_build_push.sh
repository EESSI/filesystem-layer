#!/bin/bash

if [ $# -ne 1 ]; then
    echo "ERROR: Usage: $0 <EESSI pilot version> (for example: $0 2020.10)" >&2
    exit 1
fi
eessi_pilot_version=$1

os="centos7"
cpu_arch=$(uname -m)
tag="eessi/client-pilot:${os}-${cpu_arch}-${eessi_pilot_version}"

docker build --no-cache -f Dockerfile.EESSI-client-pilot-${os}-${cpu_arch} -t ${tag} .

docker push ${tag}
