#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 EESSI contributors

echo "CVMFSEXEC Compatibility Check"
echo "=============================="
printf "%-40s %s\n" "Feature" "Status"
echo "--------------------------------------------------------------"

# Check fusermount
if command -v fusermount &>/dev/null || command -v fusermount3 &>/dev/null; then
    FUSERMOUNT="YES"
    printf "%-40s %s\n" "fusermount" "[YES]"
else
    FUSERMOUNT="NO"
    printf "%-40s %s\n" "fusermount" "[NO]"
fi

# Check user namespaces
if [ -f /proc/sys/user/max_user_namespaces ]; then
    MAX_US_NS=$(cat /proc/sys/user/max_user_namespaces)
    if [ "$MAX_US_NS" -gt 0 ] 2>/dev/null; then
        USER_NS="YES"
        printf "%-40s %s\n" "User namespaces enabled" "[YES]"
    else
        USER_NS="NO"
        printf "%-40s %s\n" "User namespaces enabled" "[NO]"
    fi
else
    USER_NS="NO"
    printf "%-40s %s\n" "User namespaces enabled" "[NO]"
fi

# Check unprivileged namespace fuse mounts
KERNEL=$(uname -r | cut -d. -f1-2)
if unshare -rm sh -c 'exit 0' &>/dev/null; then
    UNPRIV_FUSE="YES"
    printf "%-40s %s\n" "Unprivileged namespace fuse mounts" "[YES]"
else
    UNPRIV_FUSE="NO"
    printf "%-40s %s\n" "Unprivileged namespace fuse mounts" "[NO]"
fi

# Check for setuid singularity/apptainer
SETUID_SING="NO"
for cmd in singularity apptainer; do
    if command -v $cmd &>/dev/null; then
        VERSION=$($cmd --version 2>/dev/null | grep -oP '\d+\.\d+' | head -1)
        BIN=$(which $cmd)
        if [ -u "$BIN" ] || [ -u "/usr/libexec/$cmd/bin/starter-setuid" ] 2>/dev/null; then
            SETUID_SING="YES ($cmd $VERSION)"
            break
        fi
    fi
done
printf "%-40s %s\n" "Setuid singularity/apptainer >=3.4" "[$SETUID_SING]"

echo ""
echo "Supported Modes:"
echo "--------------------------------------------------------------"

if [ "$FUSERMOUNT" = "YES" ]; then
    echo "Mode 1: mountrepo/umountrepo (with container bindmount)"
fi

if [ "$FUSERMOUNT" = "YES" ] && [ "$USER_NS" = "YES" ] && [ "$UNPRIV_FUSE" = "NO" ]; then
    echo "Mode 2: cvmfsexec (user namespaces, no unpriv fuse)"
fi

if [ "$UNPRIV_FUSE" = "YES" ]; then
    echo "Mode 3: cvmfsexec (unprivileged namespace fuse mounts) * BEST"
fi

if [ "$SETUID_SING" != "NO" ]; then
    echo "Mode 4: singcvmfs (setuid singularity/apptainer)"
fi
