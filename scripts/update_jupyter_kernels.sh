#!/bin/bash

function echo_green() {
    echo -e "\e[32m$1\e[0m"
}

function echo_yellow() {
    echo -e "\e[33m$1\e[0m"
}

function echo_red() {
    echo -e "\e[31m$1\e[0m"
}

function error() {
    echo_red "ERROR: $1" >&2
    exit 1
}

# Check if a stack base dir has been specified
if [ "$#" -ne 2 ]; then
    error "usage: $0 <path to main directory of an EESSI stack> <EESSI stack version>"
fi

stack_base_dir="$1"
version_dir="$2"

# Check if the given stack base dir exists
if [ ! -d ${stack_base_dir} ]
then
  error "${stack_base_dir} does not point to an existing directory!"
fi

EB_JPT_KERNELS_REPO="https://github.com/Crivella/easybuild_jupyter_kernels.git"
EB_JPT_KERNELS_COMMIT="2b542aa5d7cb24307f5eb3f69a2591943b9139a3"
EB_JPT_PACKAGE="easybuild-jupyter-kernels"
EB_JPT_CLI="easybuild-jupyter-kernels"

# Use codes from EESSI itself to create a python venv
source "${stack_base_dir}/init/lmod/bash"

tmpdir=$(mktemp -d)
venv_dir="${tmpdir}/venv"
python -m venv "${venv_dir}" || error "Failed to create a Python virtual environment in ${venv_dir}!"

source "${venv_dir}/bin/activate" || error "Failed to activate the Python virtual environment in ${venv_dir}!"
pip install --upgrade pip || error "Failed to upgrade pip in the Python virtual environment in ${venv_dir}!"
pip install "${EB_JPT_PACKAGE}[cli] @ git+${EB_JPT_KERNELS_REPO}@${EB_JPT_KERNELS_COMMIT}"
# pip install "/home/crivella/Documents/GIT/easybuild-jupyter-kernels[cli]"

architectures=$(find ${stack_base_dir}/software/ -maxdepth 5 -type d -name modules -exec dirname {} \;)
# Create/update the Lmod cache for all CPU targets
# Only use the first arch for testing
# architectures=("${architectures[0]}")
for archdir in ${architectures}; do
    # Get the MODULEPATH that one would have by loading the EESSI stack for this architecture and version
    module purge
    arch_subdir=$(realpath --relative-to="${stack_base_dir}/software/linux" "${archdir}")
    export EESSI_SOFTWARE_SUBDIR_OVERRIDE="${arch_subdir}"
    echo "------------------------------------------------------------------------------------------------------------"
    echo_yellow "Loading EESSI stack version ${version_dir} for architecture ${EESSI_SOFTWARE_SUBDIR_OVERRIDE}..."
    module load EESSI/${version_dir}
    ARCH_MODULEPATH="$MODULEPATH"
    ARCH_EPREFIX="$EESSI_EPREFIX"

    # Run using a viable architecture during `module load EESSI` to get compat layer binaries that works, but replace
    # the module loaded with the actual architecture we want to update the kernels for
    # NOTE: this assumes that the `module load` results do not rely on having the binaries for the proper architecture.
    module purge
    export EESSI_SOFTWARE_SUBDIR_OVERRIDE=""
    module load EESSI/${version_dir}
    MODULEPATH="${ARCH_MODULEPATH}"

    # Ensure the compat layer binaries are in the PATH in case the kernels uses them to run commands
    # Append them so that the correect binaries for the actual architecture are used first when running `module load``
    PREVIOUS_PATH="${PATH}"
    export PATH="${PATH}:${ARCH_EPREFIX}/bin:${ARCH_EPREFIX}/usr/bin"

    export EB_JUPYTER_KERNEL_DISPLAY_PREFIX="EESSI/${version_dir} -"
    # --filter-paths: Only pickup kernels from directories that match the given regex pattern
    # --filter-env-paths: Filter PATH-like environment variables to only include directories that match the given
    #                     regex pattern (multiple --filter-env-paths imply OR logic)
    ${EB_JPT_CLI} store-kernels \
        --filter-paths "^${stack_base_dir}/software/linux/${arch_subdir}/" \
        --filter-env-paths "^${stack_base_dir}/software/linux/${arch_subdir}/" \
        --filter-env-paths "^${ARCH_EPREFIX}.*/bin$" \
        ${tmpdir}/output/kernels

    # Restore the previous PATH so that `module purge` does not leave the manually added paths potentially causing
    # issues for the next architecture in the loop
    export PATH="${PREVIOUS_PATH}"

    exit_code=$?
    if [[ ${exit_code} -eq 0 ]]; then
        echo_green "Updated the Jupyter kernels for ${archdir}."
    else
        error "Failed to update the Jupyter kernels for ${archdir}!"
    fi

    # Keep a backup of the existing kernels, and move the new kernels to the proper location
    KERNEL_DIR="${stack_base_dir}/software/linux/${arch_subdir}/.jupyter/kernels"
    if [ -d "${KERNEL_DIR}" ]; then
        BACKUP_DIR="${KERNEL_DIR}.bak_$(date +%Y%m%d_%H%M%S)"
        echo_yellow "Moving existing Jupyter kernels for ${archdir} to ${BACKUP_DIR} ..."
        mv "${KERNEL_DIR}" "${BACKUP_DIR}" || error "Failed to move existing Jupyter kernels for ${archdir} to a backup directory!"
    fi
    mkdir -p "${KERNEL_DIR}" || error "Failed to create the Jupyter kernels directory for ${archdir}!"
    mv ${tmpdir}/output/kernels/* "${KERNEL_DIR}/" || error "Failed to move the new Jupyter kernels for ${archdir} to the target directory!"
done
