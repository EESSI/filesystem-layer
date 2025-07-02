#/bin/bash
cvmfsversion=$1
arch=$(dpkg --print-architecture)

apt-get update
apt-get install -y wget lsb-release

distro=$(lsb_release -si | tr [:upper:] [:lower:])
release=$(lsb_release -sr)

os="${distro}${release}"

if [ "$arch" = "riscv64" ]
then
    apt-get install -y devscripts libfuse3-dev cmake cpio golang libcap-dev libssl-dev libfuse-dev pkg-config libattr1-dev python3-dev python3-setuptools python3-dev python3-setuptools uuid-dev libz-dev lsb-release
    cd /tmp
    wget https://github.com/cvmfs/cvmfs/archive/refs/tags/cvmfs-${cvmfsversion}.tar.gz
    tar xzf cvmfs-${cvmfsversion}.tar.gz
    cd cvmfs-cvmfs-${cvmfsversion}
    mkdir /root/deb
    sed -i 's/amd64 armhf arm64/amd64 armhf arm64 riscv64/' packaging/debian/cvmfs/control*
    # debian13 provides libfuse3-4, see https://github.com/cvmfs/cvmfs/pull/3847
    [ $os = "debian13" ] && sed -i 's/libfuse3-3 (>= 3.3.0)/libfuse3-3 (>= 3.3.0) | libfuse3-4/g' packaging/debian/cvmfs/control*
    # valgrind is not available (yet) for RISC-V
    sed -i 's/, valgrind//' packaging/debian/cvmfs/control*
    # QEMU shows the host CPU in /proc/cpuinfo, so we need to tweak the CPU detection for some packages and use uname -m instead
    sed -i "s/^ISA=.*/ISA=\$(uname -m)/" externals/libcrypto/src/configureHook.sh
    sed -i "s/rv64/riscv64/" externals/libcrypto/src/configureHook.sh
    sed -i "s/^ISA=.*/ISA=\$(uname -m)/" externals/protobuf/src/configureHook.sh
    sed -i "s/rv64/riscv64/" externals/protobuf/src/configureHook.sh

    cd ci/cvmfs
    ./deb.sh /tmp/cvmfs-cvmfs-${cvmfsversion} /root/deb
else
    mkdir -p /root/deb
    cd /root/deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs_${cvmfsversion}~1+${os}_${arch}.deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-fuse3_${cvmfsversion}~1+${os}_${arch}.deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-libs_${cvmfsversion}~1+${os}_${arch}.deb
    wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-shrinkwrap_${cvmfsversion}~1+${os}_${arch}.deb
fi

cd /root/deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-config/cvmfs-config-default_latest_all.deb
wget https://github.com/EESSI/filesystem-layer/releases/download/latest/cvmfs-config-eessi_latest_all.deb
