cvmfsversion=$1
arch=$(uname -m)

yum install -y wget
if [ "$arch" = "ppc64le" ]
then
    # build RPMs using the source RPMs
    yum install -y epel-release
    yum install -y rpm-build checkpolicy cmake fuse-devel fuse3-devel gcc gcc-c++ golang libattr-devel libcap-devel libuuid-devel openssl-devel python2-devel python2-setuptools selinux-policy-devel valgrind-devel hardlink selinux-policy-targeted
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-${cvmfsversion}-1.el7.src.rpm && rpmbuild --rebuild cvmfs-${cvmfsversion}-1.el7.src.rpm
else
    # just download the available RPMs
    mkdir -p /root/rpmbuild/RPMS/${arch}
    cd /root/rpmbuild/RPMS/${arch}
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-${cvmfsversion}-1.el7.${arch}.rpm
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-fuse3-${cvmfsversion}-1.el7.${arch}.rpm
fi
