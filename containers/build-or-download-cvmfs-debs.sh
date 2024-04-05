#/bin/bash
cvmfsversion=$1
arch=$(dpkg --print-architecture)

apt-get update
apt-get install -y wget lsb-release

distro=$(lsb_release -si | tr [:upper:] [:lower:])
release=$(lsb_release -sr)

# lsb_release -sr prints n/a for debian sid, replace it by 13
if [ "${distro}" = "debian" ] && [ "${release}" = "n/a" ]
then
    release=13
fi

os="${distro}${release}"

if [ "$arch" = "arm64" ] || [ "$arch" = "riscv64" ] || [ "${os}" = "debian13" ]
then
    apt-get install -y devscripts libfuse3-dev cmake cpio libcap-dev libssl-dev libfuse-dev pkg-config libattr1-dev python3-dev python3-setuptools python3-dev python3-setuptools uuid-dev libz-dev lsb-release
    cd /tmp
    wget https://github.com/cvmfs/cvmfs/archive/refs/tags/cvmfs-${cvmfsversion}.tar.gz
    tar xzf cvmfs-${cvmfsversion}.tar.gz
    cd cvmfs-cvmfs-${cvmfsversion}/ci/cvmfs
    mkdir /root/deb
    sed -i 's/Architecture: i386 amd64 armhf arm64/Architecture: i386 amd64 armhf arm64 riscv64/' ../../packaging/debian/cvmfs/control.in
    sed -i 's/python-dev/python3-dev/' ../../packaging/debian/cvmfs/control.in
    sed -i 's/python-setuptools/python3-setuptools/' ../../packaging/debian/cvmfs/control.in
    # valgrind is not available (yet) for RISC-V
    if [ "$arch" = "riscv64" ]
    then
        sed -i 's/, valgrind//' ../../packaging/debian/cvmfs/control.in
    else
        apt-get install -y valgrind
    fi
    # make sure the cvmfs package also uses debian 13 for debian sid
    [ $release = "13" ] && sed -i "s@\$(lsb_release -sr)@13@" ./deb.sh
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
