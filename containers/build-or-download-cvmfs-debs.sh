#/bin/bash
cvmfsversion=$1

apt-get update
apt-get install -y wget lsb-release

arch=$(dpkg --print-architecture)
os="$(lsb_release -si | tr [:upper:] [:lower:])$(lsb_release -sr)"

if [ "$arch" = "ppc64el" ] || [ "$arch" = "arm64" ]
then
    apt-get install -y devscripts libfuse3-dev cmake cpio libcap-dev libssl-dev libfuse-dev pkg-config libattr1-dev python-dev python-setuptools python3-dev python3-setuptools uuid-dev valgrind libz-dev lsb-release
    # Set Python 2 as default Python
    update-alternatives --install /usr/bin/python python /usr/bin/python2 1
    update-alternatives --install /usr/bin/python python /usr/bin/python3 2
    cd /tmp
    wget https://github.com/cvmfs/cvmfs/archive/refs/tags/cvmfs-${cvmfsversion}.tar.gz
    tar xzf cvmfs-${cvmfsversion}.tar.gz
    cd cvmfs-cvmfs-${cvmfsversion}/ci/cvmfs
    mkdir /root/deb
    sed -i 's/Architecture: i386 amd64 armhf arm64/Architecture: i386 amd64 armhf arm64 ppc64el/' ../../packaging/debian/cvmfs/control.in
    ./deb.sh /tmp/cvmfs-cvmfs-${cvmfsversion} /root/deb
else
    mkdir -p /root/deb
    cd /root/deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs_${cvmfsversion}~1+${os}_${arch}.deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-fuse3_${cvmfsversion}~1+${os}_${arch}.deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-libs_${cvmfsversion}~1+${os}_${arch}.deb
fi

cd /root/deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-config/cvmfs-config-default_latest_all.deb
wget https://github.com/EESSI/filesystem-layer/releases/download/latest/cvmfs-config-eessi_latest_all.deb
