#!/usr/bin/env python3
#
# Create admin.list file for Lmod.
# This will use information from the known_issues.yaml file to display
# a message to the user when they load a module that is known to have issues.
import os
import yaml
from urllib import request


# Download the known issues YAML file from the EESSI/software-layer GitHub repository
# TODO: This hardcodes version 2023.06, we should make this dynamic
KNOWN_ISSUES_FILE = 'eessi-2023.06-known-issues.yml'
KNOWN_ISSUES_URL = 'https://raw.githubusercontent.com/EESSI/software-layer/2023.06-software.eessi.io/' + KNOWN_ISSUES_FILE
r = request.urlretrieve(KNOWN_ISSUES_URL, KNOWN_ISSUES_FILE)

# Open the YAML file
try:
    with open(KNOWN_ISSUES_FILE, 'r') as file:
        # Load the YAML data
        known_issues = yaml.safe_load(file)
except IOError:
    raise IOError("Unable to open the known issues file")

# Create a admin.list file per arch
path = '/cvmfs/software.eessi.io/versions/2023.06/software/linux/'
for i in range(len(known_issues)):
    arch, known_issues_arch = list(known_issues[i].items())[0]
    admin_list_filename = f"admin.list.{arch}"

    # Remove the admin.list file if it exists, we will recreate it
    if os.path.exists(admin_list_filename):
        try:
            os.remove(admin_list_filename)
        except OSError:
            raise OSError(f"Unable to remove the {admin_list_filename} file")

    # Open the admin.list file, with no dashes in the filename
    admin_list_file = open(admin_list_filename.replace('/', '_'), 'a')
    for j in range(len(known_issues_arch)):
        # Write known issue per arch and module
        known_issues_module, known_issue = list(known_issues_arch[j].items())[0]
        known_issues_module = known_issues_module.replace('/', '_')
        module_path = os.path.join(path, 'modules/all', arch, known_issues_module)
        message = f"{module_path}:"
        message += (
            f"\n   There is a known issue: {known_issue[1]['info']}"
            f"\n   See: {known_issue[0]['issue']}\n\n"
        )
        admin_list_file.write(message)

admin_list_file.close()
