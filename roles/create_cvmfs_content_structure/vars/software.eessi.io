# Specifications of files and symlinks for the software.eessi.io CVMFS repository.
# Paths for files and symlinks should be relative to the root of the repository.
---
files:
  - name: .cvmfsdirtab
    dest: ''
    mode: '644'

symlinks:
  latest: versions/2023.06
  host_injections: '$(EESSI_HOST_INJECTIONS:-/opt/eessi)'
