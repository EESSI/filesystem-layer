#!/bin/bash

INGEST_SCRIPT=$(dirname "$(realpath $0)")/ingest-tarball.sh

# Temporary base dir for the tests
tstdir=$(mktemp -d)

# Statistics
num_tests=0
num_tests_failed=0
num_tests_succeeded=0

function create_tarball() {
  # Create a tarball with a given name, version directory,
  # and contents type directory
  tarball="$1"
  version_dir="$2"
  type_dir="$3"

  # Create a temporary directory with the dummy contents of the tarball
  tartmpdir=$(mktemp -d -p "${tstdir}")
  mkdir -p "$tartmpdir/$version_dir/$type_dir"
  touch "$tartmpdir/$version_dir/$type_dir/somefile"

  tar czf "$tarball" -C "$tartmpdir" "$version_dir/$type_dir"
  rm -rf "${tartmpdir}"
  echo "$tarball"
}

# Create a fake cvmfs_server executable, and prepend it to $PATH
cat << EOF > "${tstdir}/cvmfs_server"
#!/bin/bash
if [ \$# -lt 2 ]; then
  echo "cvmfs_server expects at least two arguments!"
  exit 1
fi
echo "Calling: cvmfs_server \$@"
EOF
chmod +x "${tstdir}/cvmfs_server"
export PATH="${tstdir}:$PATH"

# Tests that should succeed
tarballs_success=(
  "$tstdir/eessi-2000.01-compat-linux-x86_64-123456.tar.gz 2000.01 compat/linux/x86_64"
  "$tstdir/eessi-2000.01-compat-linux-aarch64-123456.tar.gz 2000.01 compat/linux/aarch64"
  "$tstdir/eessi-2000.01-compat-linux-riscv64-123456.tar.gz 2000.01 compat/linux/riscv64"
  "$tstdir/eessi-2000.01-compat-linux-ppc64le-123456.tar.gz 2000.01 compat/linux/ppc64le"
  "$tstdir/eessi-2000.01-compat-macos-x86_64-123456.tar.gz 2000.01 compat/macos/x86_64"
  "$tstdir/eessi-2000.01-init-123456.tar.gz 2000.01 init"
  "$tstdir/eessi-2000.01-software-123456.tar.gz 2000.01 software/linux/x86_64/intel/haswell"
)

# Test that should return an error
tarballs_fail=(
  # Non-matching type dirs
  "$tstdir/eessi-2000.01-compat-123456.tar.gz 2000.01 init"
  "$tstdir/eessi-2000.01-init-123456.tar.gz 2000.01 initt"
  "$tstdir/eessi-2000.01-software-123456.tar.gz 2000.01 soft"
  # Non-matching versions
  "$tstdir/eessi-2000.01-compat-123456.tar.gz 2000.12 compat"
  "$tstdir/eessi-2000.01-init-123456.tar.gz 2000.12 init"
  "$tstdir/eessi-2000.01-software-123456.tar.gz 20.12 software"
  # Invalid contents type
  "$tstdir/eessi-2000.01-something-123456.tar.gz 2000.01 software"
  # Invalid version number
  "$tstdir/eessi-2000.13-software-123456.tar.gz 2000.13 software"
  # Missing version in filename
  "$tstdir/eessi-software-123456.tar.gz 2000.01 software"
  # Missing version directory in tarball contents
  "$tstdir/eessi-2000.01-compat-123456.tar.gz compat linux"
  "$tstdir/eessi-2000.01-init-123456.tar.gz init Magic_Castle"
  "$tstdir/eessi-2000.01-software-123456.tar.gz software linux"
  # Invalid operating system
  "$tstdir/eessi-2000.01-compat-123456.tar.gz 2000.01 compat/windows/x86_64"
  "$tstdir/eessi-2000.01-compat-123456.tar.gz 2000.01 compat/windows"
  # Invalid architecture
  "$tstdir/eessi-2000.01-compat-123456.tar.gz 2000.01 compat/linux/sparc"
  "$tstdir/eessi-2000.01-compat-123456.tar.gz 2000.01 compat"
)

# Run the tests that should succeed
for ((i = 0; i < ${#tarballs_success[@]}; i++)); do
    t=$(create_tarball ${tarballs_success[$i]})
    "${INGEST_SCRIPT}" "$t" > /dev/null
    if [ ! $? -eq 0 ]; then
        num_tests_failed=$((num_tests_failed + 1))
    else
        num_tests_succeeded=$((num_tests_succeeded + 1))
    fi
    num_tests=$((num_tests + 1))
done

# Run the tests that should fail
for ((i = 0; i < ${#tarballs_fail[@]}; i++)); do
    t=$(create_tarball ${tarballs_fail[$i]})
    "${INGEST_SCRIPT}" "$t" >& /dev/null
    if [ ! $? -eq 1 ]; then
        num_tests_failed=$((num_tests_failed + 1))
    else
        num_tests_succeeded=$((num_tests_succeeded + 1))
    fi
    num_tests=$((num_tests + 1))
done

# Clean up
rm -rf "${tstdir}"

# Print some statistics, and exit with a return code based on whether tests have failed
echo "Ran ${num_tests} tests, ${num_tests_succeeded} succeeded, ${num_tests_failed} failed."
if [ ${num_tests_failed} -eq 0 ]; then
  exit 0
else
  exit 1
fi
