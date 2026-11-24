#/bin/bash
cvmfsversion=$1
arch=$(dpkg --print-architecture)

apt-get update && apt-get upgrade -y
apt-get install -y wget lsb-release

distro=$(lsb_release -si | tr [:upper:] [:lower:])
release=$(lsb_release -sr)

os="${distro}${release}"

mkdir -p /root/deb
cd /root/deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs_${cvmfsversion}+${os}_${arch}.deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-fuse3_${cvmfsversion}+${os}_${arch}.deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-libs_${cvmfsversion}+${os}_${arch}.deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-shrinkwrap_${cvmfsversion}+${os}_${arch}.deb

cd /root/deb
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-config/cvmfs-config-default_latest_all.deb
wget https://github.com/EESSI/filesystem-layer/releases/download/latest/cvmfs-config-eessi_latest_all.deb
