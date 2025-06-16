from dataclasses import dataclass
import tarfile
from pathlib import PurePosixPath
import os

from eessi_data_object import EESSIDataAndSignatureObject
from utils import log_function_entry_exit
from remote_storage import DownloadMode


@dataclass
class EESSITaskPayload:
    """Class representing an EESSI task payload (tarball/artifact) and its signature."""

    # The EESSI data and signature object associated with this payload
    payload_object: EESSIDataAndSignatureObject

    # Whether the signature was successfully verified
    signature_verified: bool = False

    # possibly at a later point in time, we will add inferred metadata here
    # such as the prefix in a tarball, the main elements, or which software
    # package it includes

    @log_function_entry_exit()
    def __init__(self, payload_object: EESSIDataAndSignatureObject):
        """
        Initialize an EESSITaskPayload object.

        Args:
            payload_object: The EESSI data and signature object associated with this payload
        """
        self.payload_object = payload_object

        # Download the payload and its signature
        self.payload_object.download(mode=DownloadMode.CHECK_REMOTE)

        # Verify signature
        self.signature_verified = self.payload_object.verify_signature()

    @log_function_entry_exit()
    def analyse_contents(self) -> str:
        """Analyse the contents of the payload and return a summary in a ready-to-use HTML format."""
        tar = tarfile.open(self.payload_object.local_file_path, 'r')
        members = tar.getmembers()
        tar_num_members = len(members)
        paths = sorted([m.path for m in members])

        if tar_num_members < 100:
            tar_members_desc = "Full listing of the contents of the tarball:"
            members_list = paths

        else:
            tar_members_desc = "Summarized overview of the contents of the tarball:"
            # determine prefix after filtering out '<EESSI version>/init' subdirectory,
            # to get actual prefix for specific CPU target (like '2023.06/software/linux/aarch64/neoverse_v1')
            init_subdir = os.path.join('*', 'init')
            non_init_paths = sorted(
                [path for path in paths if not any(parent.match(init_subdir) for parent in PurePosixPath(path).parents)]
            )
            if non_init_paths:
                prefix = os.path.commonprefix(non_init_paths)
            else:
                prefix = os.path.commonprefix(paths)

            # TODO: this only works for software tarballs, how to handle compat layer tarballs?
            swdirs = [  # all directory names with the pattern: <prefix>/software/<name>/<version>
                member.path
                for member in members
                if member.isdir() and PurePosixPath(member.path).match(os.path.join(prefix, 'software', '*', '*'))
            ]
            modfiles = [  # all filenames with the pattern: <prefix>/modules/<category>/<name>/*.lua
                member.path
                for member in members
                if member.isfile() and
                PurePosixPath(member.path).match(os.path.join(prefix, 'modules', '*', '*', '*.lua'))
            ]
            other = [  # anything that is not in <prefix>/software nor <prefix>/modules
                member.path
                for member in members
                if (not PurePosixPath(prefix).joinpath('software') in PurePosixPath(member.path).parents
                    and not PurePosixPath(prefix).joinpath('modules') in PurePosixPath(member.path).parents)
                # if not fnmatch.fnmatch(m.path, os.path.join(prefix, 'software', '*'))
                # and not fnmatch.fnmatch(m.path, os.path.join(prefix, 'modules', '*'))
            ]
            members_list = sorted(swdirs + modfiles + other)

        # Construct the overview.
        tar_members = '\n'.join(members_list)
        overview = f"Total number of items in the tarball: {tar_num_members}"
        overview += f"\nURL to the tarball: {self.url}"
        overview += f"\n{tar_members_desc}\n"
        overview += f"```\n{tar_members}\n```"

        # Make sure that the overview does not exceed Github's maximum length (65536 characters).
        if len(overview) > 60000:
            overview = overview[:60000] + "\n\nWARNING: output exceeded the maximum length and was truncated!\n```"
        return overview

    @log_function_entry_exit()
    def __str__(self) -> str:
        """Return a string representation of the EESSITaskPayload object."""
        return f"EESSITaskPayload({self.payload_object.local_file_path}, verified={self.signature_verified})"
