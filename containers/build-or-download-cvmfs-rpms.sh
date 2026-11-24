cvmfsversion=$1
arch=$(uname -m)

yum install -y wget
yum update -y
elversion="$(rpm -q --queryformat '%{RELEASE}' rpm | cut -d '.' -f 2 | cut -d '_' -f 1)"

mkdir -p /root/rpmbuild/RPMS/${arch}
cd /root/rpmbuild/RPMS/${arch}
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-${cvmfsversion}-1.${elversion}.${arch}.rpm
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-fuse3-${cvmfsversion}-1.${elversion}.${arch}.rpm
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-libs-${cvmfsversion}-1.${elversion}.${arch}.rpm
wget https://ecsft.cern.ch/dist/cvmfs/cvmfs-${cvmfsversion}/cvmfs-shrinkwrap-${cvmfsversion}-1.${elversion}.${arch}.rpm
