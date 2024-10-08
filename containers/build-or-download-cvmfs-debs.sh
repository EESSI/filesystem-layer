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
    cd cvmfs-cvmfs-${cvmfsversion}
    mkdir /root/deb
    sed -i 's/Architecture: i386 amd64 armhf arm64/Architecture: i386 amd64 armhf arm64 riscv64/' packaging/debian/cvmfs/control.in
    sed -i 's/python-dev/python3-dev/' packaging/debian/cvmfs/control.in
    sed -i 's/python-setuptools/python3-setuptools/' packaging/debian/cvmfs/control.in
    if [ "$arch" = "riscv64" ]
    then
        # valgrind is not available (yet) for RISC-V
        sed -i 's/, valgrind//' packaging/debian/cvmfs/control.in
        # for RISC-V we need to run autoreconf, see:
        # https://github.com/cvmfs/cvmfs/pull/3446
        wget https://github.com/cvmfs/cvmfs/pull/3446.patch
        patch -p 1 -i ./3446.patch
        rm 3446.patch
        # QEMU shows the host CPU in /proc/cpuinfo, so we need to tweak the CPU detection for some packages and use uname -m instead
        sed -i "s/^ISA=.*/ISA=\$(uname -m)/" externals/libcrypto/src/configureHook.sh
        sed -i "s/rv64/riscv64/" externals/libcrypto/src/configureHook.sh
        sed -i "s/^ISA=.*/ISA=\$(uname -m)/" externals/protobuf/src/configureHook.sh
        sed -i "s/rv64/riscv64/" externals/protobuf/src/configureHook.sh
    else
        apt-get install -y valgrind
    fi

    # gcc 14 fix for CVMFS's dependency pacparser, see
    # https://github.com/manugarg/pacparser/issues/194
    if gcc --version | grep -q "^gcc.*14"; then
cat << EOF > externals/pacparser/src/fix_gcc14.patch
--- src/spidermonkey/js/src/jsapi.c
+++ src/spidermonkey/js/src/jsapi.c
@@ -93,7 +93,7 @@
 #ifdef HAVE_VA_LIST_AS_ARRAY
 #define JS_ADDRESSOF_VA_LIST(ap) ((va_list *)(ap))
 #else
-#define JS_ADDRESSOF_VA_LIST(ap) (&(ap))
+#define JS_ADDRESSOF_VA_LIST(ap) ((va_list *)(&(ap)))
 #endif
 
 #if defined(JS_PARANOID_REQUEST) && defined(JS_THREADSAFE)
EOF
    fi

    cd ci/cvmfs
    # make sure the cvmfs package also uses debian 13 for debian sid
    [ $release = "13" ] && sed -i "s@\$(lsb_release -sr)@13@" ./deb.sh && sed -i "s/focal/trixie/" ./deb.sh
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
