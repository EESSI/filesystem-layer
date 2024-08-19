#!/usr/bin/env python3
#
# Create admin.list file for Lmod.
# This will use information from the known_issues.yaml file to display
# a message to the user when they load a module that is known to have issues.
#
import os
import yaml
from urllib import request

# Download the known issues YAML file from the EESSI/software-layer GitHub repository


# Get known issues file
# TODO: This hardcodes version 2023.06, we should make this dynamic
url = 'https://raw.githubusercontent.com/EESSI/software-layer/2023.06-software.eessi.io/eessi-2023.06-known-issues.yml'
r = request.urlretrieve(url, 'eessi-2023.06-known-issues.yml')

# Open the YAML file
with open('eessi-2023.06-known-issues.yml', 'r') as file:
    # Load the YAML data
    known_issues = yaml.safe_load(file)

# Remove the admin.list file if it exists, we will recreate it
if os.path.exists('admin.list'):
    os.remove('admin.list')


admin_list_file = open('admin.list', 'a')
path = '/cvmfs/software.eessi.io/versions/2023.06/software/linux/'
for i in range(len(known_issues)):
    arch, known_issues_arch = list(known_issues[i].items())[0]
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
