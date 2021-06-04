cvmfsversion=$1
arch=$(dpkg --print-architecture)

apt-get update
apt-get install -y wget
if [ "$arch" = "ppc64el" ] || [ "$arch" = "arm64" ]
then
    apt-get install devscripts libfuse3-dev cmake cpio libcap-dev libssl-dev libfuse-dev pkg-config libattr1-dev python-dev python-setuptools uuid-dev valgrind libz-dev lsb-release
    cd /tmp
    wget https://github.com/cvmfs/cvmfs/archive/refs/tags/cvmfs-${cvmfsversion}.tar.gz
    tar xzf cvmfs-${cvmfsversion}.tar.gz
    cd cvmfs-cvmfs-${cvmfsversion}/ci/cvmfs
    mkdir /root/deb
    ./deb.sh /tmp/cvmfs-cvmfs-${cvmfsversion} /root/deb
else
    mkdir -p /root/deb
    cd /root/deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs_${cvmfsversion}~1+debian10_${arch}.deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-fuse3_${cvmfsversion}~1+debian10_${arch}.deb
fi

cd /root/deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-config/cvmfs-config-default_latest_all.deb
wget https://github.com/EESSI/filesystem-layer/releases/download/latest/cvmfs-config-eessi_latest_all.deb
