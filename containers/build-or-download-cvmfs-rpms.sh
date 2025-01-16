cvmfsversion=$1
arch=$(uname -m)

yum install -y wget
elversion="$(rpm -q --queryformat '%{RELEASE}' rpm | cut -d '.' -f 2)"
if [ "$arch" = "riscv64" ]
then
    yum install -y epel-release
    yum install -y rpm-build checkpolicy cmake fuse-devel fuse3-devel gcc gcc-c++ golang libattr-devel libcap-devel libuuid-devel openssl-devel python-devel python-setuptools python3-devel python3-setuptools selinux-policy-devel valgrind-devel hardlink selinux-policy-targeted
    # Set Python 2 as default Python
    update-alternatives --install /usr/bin/python python /usr/bin/python3 1
    update-alternatives --install /usr/bin/python python /usr/bin/python2 2
    update-alternatives --set python /usr/bin/python2
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-${cvmfsversion}-1.${elversion}.src.rpm && rpmbuild --rebuild cvmfs-${cvmfsversion}-1.${elversion}.src.rpm
else
    mkdir -p /root/rpmbuild/RPMS/${arch}
    cd /root/rpmbuild/RPMS/${arch}
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-${cvmfsversion}-1.${elversion}.${arch}.rpm
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-fuse3-${cvmfsversion}-1.${elversion}.${arch}.rpm
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-libs-${cvmfsversion}-1.${elversion}.${arch}.rpm
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-shrinkwrap-${cvmfsversion}-1.${elversion}.${arch}.rpm
fi
