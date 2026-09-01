from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict

import os
import sys
if sys.version_info >= (3, 14):
    import tarfile
else:
    from backports.zstd import tarfile

from eessi_data_object import EESSIDataAndSignatureObject
from eessi_logging import log_function_entry_exit
from eessi_remote_storage_client import DownloadMode


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

        # download the payload and its signature
        self.payload_object.download(mode=DownloadMode.CHECK_REMOTE)

        # verify signature
        self.signature_verified = self.payload_object.verify_signature()

    @log_function_entry_exit()
    def analyse_contents(self, config: Dict) -> str:
        """Analyse the contents of the payload and return a summary in a ready-to-use HTML format."""
        tar = tarfile.open(self.payload_object.local_file_path, "r")
        members = tar.getmembers()
        tar_num_members = len(members)
        paths = sorted([m.path for m in members])

        # reduce limit for full listing from 100 to 3 because the description can
        # include 10s of tarballs and thus even 100 maybe too many; using a very
        # small number can still be useful if there is only a very small number
        # of files, say an architecture specific configuration file
        if tar_num_members < 3:
            tar_members_desc = "Full listing of the contents of the tarball:"
            members_list = paths

        else:
            tar_members_desc = "Summarized overview of the contents of the tarball:"

            # TODO: this only works for software tarballs, how to handle compat layer tarballs?
            swdirs = [  # all directory names with the pattern: <prefix>/software/<name>/<version>
                member.path
                for member in members
                if member.isdir() and PurePosixPath(member.path).match(os.path.join('**', 'software', '*', '*'))
            ]
            modfiles = [  # all filenames with the pattern: <prefix>/modules/<category>/<name>/*.lua
                member.path
                for member in members
                if member.isfile()
                and PurePosixPath(member.path).match(os.path.join('**', 'modules', '*', '*', '*.lua'))
            ]
            reprod_dirs = [  # reprod dirs with the pattern: <prefix>/reprod/<name>/<version>/<timestamp>
                member.path
                for member in members
                if member.isdir() and PurePosixPath(member.path).match(os.path.join('**', 'reprod', '*', '*', '*'))
            ]
            # the following may detect other files, but full_match functionality requires Python 3.13 or newer
            # other = [  # anything that does not have software, modules, nor reprod in its path
            #     member.path
            #     for member in members
            #     if (
            #           not PurePosixPath(member.path).full_match(os.path.join('**', 'software', '**'))
            #           and not PurePosixPath(member.path).full_match(os.path.join('**', 'modules', '**'))
            #           and not PurePosixPath(member.path).full_match(os.path.join('**', 'reprod', '**'))
            #     )
            # ]

            # more basic approach to find any other files/directories included in the tarball
            other = []
            for member in members:
                # skip files/dirs that are inside software directories
                if any([PurePosixPath(member.path).is_relative_to(sw_dir) for sw_dir in swdirs]):
                    continue
                # skip files/dirs that are in a reprod directory or which is a parent directory of a reprod directory
                elif any([PurePosixPath(member.path).is_relative_to(reprod_dir) or
                          PurePosixPath(reprod_dir).parent.match(member.path)
                          for reprod_dir in reprod_dirs]):
                    continue
                # skip already found module files
                elif member.path in modfiles:
                    continue

                other.append(member.path)

            # remove duplicates by converting to a set, and then sort
            members_list = sorted(set(swdirs + modfiles + reprod_dirs + other))

        # construct the overview
        overview = config["github"]["task_summary_payload_overview_template"].format(
            tar_num_members=tar_num_members,
            bucket_url=self.payload_object.remote_client.get_bucket_url(),
            remote_file_path=self.payload_object.remote_file_path,
            tar_members_desc=tar_members_desc,
            tar_members="\n".join(members_list)
        )

        # make sure that the overview does not exceed Github's maximum length (65536 characters)
        if len(overview) > 60000:
            overview = overview[:60000] + "\n\nWARNING: output exceeded the maximum length and was truncated!\n```"
        return overview

    @log_function_entry_exit()
    def __str__(self) -> str:
        """Return a string representation of the EESSITaskPayload object."""
        return f"EESSITaskPayload({self.payload_object.local_file_path}, verified={self.signature_verified})"
