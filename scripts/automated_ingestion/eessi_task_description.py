from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import json

from eessi_data_object import EESSIDataAndSignatureObject
from eessi_logging import log_function_entry_exit, log_message, LoggingScope
from eessi_remote_storage_client import DownloadMode


@dataclass
class EESSITaskDescription:
    """Class representing an EESSI task to be performed, including its metadata and associated data files."""

    # The EESSI data and signature object associated with this task
    task_object: EESSIDataAndSignatureObject

    # Whether the signature was successfully verified
    signature_verified: bool = False

    # Metadata from the task description file
    metadata: Dict[str, Any] = None

    # task element
    task: Dict[str, Any] = None

    # source element
    source: Dict[str, Any] = None

    @log_function_entry_exit()
    def __init__(self, task_object: EESSIDataAndSignatureObject):
        """
        Initialize an EESSITaskDescription object.

        Args:
            task_object: The EESSI data and signature object associated with this task
        """
        self.task_object = task_object
        self.metadata = {}

        self.task_object.download(mode=DownloadMode.CHECK_REMOTE)

        # verify signature and set initial state
        self.signature_verified = self.task_object.verify_signature()

        # try to read metadata (will only succeed if signature is verified)
        try:
            self._read_metadata()
        except RuntimeError:
            # expected if signature is not verified yet
            pass

        # check if the task file contains a task field and add that to self
        if "task" in self.metadata:
            self.task = self.metadata["task"]
        else:
            self.task = None

        # check if the task file contains a link2pr field and add that to source element
        if "link2pr" in self.metadata:
            self.source = self.metadata["link2pr"]
        else:
            self.source = None

    @log_function_entry_exit()
    def get_contents(self) -> str:
        """
        Get the contents of the task description / metadata file.
        """
        return self.raw_contents

    @log_function_entry_exit()
    def get_metadata_filename_components(self) -> Tuple[str, str, str, str, str, str]:
        """
        Get the components of the metadata file name.

        An example of the metadata file name is:
          eessi-2023.06-software-linux-x86_64-amd-zen2-1745557626.tar.gz.meta.txt

        The components are:
          eessi: some prefix
          VERSION: 2023.06
          COMPONENT: software
          OS: linux
          ARCHITECTURE: x86_64-amd-zen2
          TIMESTAMP: 1745557626
          SUFFIX: tar.gz.meta.txt

          The ARCHITECTURE component can include one to two hyphens.
          The SUFFIX is the part after the first dot (no other components should include dots).
        """
        # obtain file name from local file path using basename
        file_name = Path(self.task_object.local_file_path).name
        # split file_name into part before suffix and the suffix
        #   idea: split on last hyphen, then split on first dot
        suffix = file_name.split("-")[-1].split(".", 1)[1]
        file_name_without_suffix = file_name.strip(f".{suffix}")
        # from file_name_without_suffix determine VERSION (2nd element), COMPONENT (3rd element), OS (4th element),
        #  ARCHITECTURE (5th to second last elements) and TIMESTAMP (last element)
        components = file_name_without_suffix.split("-")
        version = components[1]
        component = components[2]
        os = components[3]
        architecture = "-".join(components[4:-1])
        timestamp = components[-1]
        return version, component, os, architecture, timestamp, suffix

    @log_function_entry_exit()
    def get_metadata_value(self, key: str) -> str:
        """
        Get the value of a key from the task description / metadata file.
        """
        # check that key is defined and has a length > 0
        if not key or len(key) == 0:
            raise ValueError("get_metadata_value: key is not defined or has a length of 0")

        value = None
        task = self.task
        source = self.source
        # check if key is in task or source
        if task and key in task:
            value = task[key]
            log_message(LoggingScope.TASK_OPS, "INFO",
                        f"Value '{value}' for key '{key}' found in information from task metadata: {task}")
        elif source and key in source:
            value = source[key]
            log_message(LoggingScope.TASK_OPS, "INFO",
                        f"Value '{value}' for key '{key}' found in information from source metadata: {source}")
        else:
            log_message(LoggingScope.TASK_OPS, "INFO",
                        f"Value for key '{key}' neither found in task metadata nor source metadata")
            raise ValueError(f"Value for key '{key}' neither found in task metadata nor source metadata")
        return value

    @log_function_entry_exit()
    def get_pr_number(self) -> str:
        """
        Get the PR number from the task description / metadata file.
        """
        return self.get_metadata_value("pr")

    @log_function_entry_exit()
    def get_repo_name(self) -> str:
        """
        Get the repository name from the task description / metadata file.
        """
        return self.get_metadata_value("repo")

    @log_function_entry_exit()
    def get_task_file_name(self) -> str:
        """
        Get the file name from the task description / metadata file.
        """
        # get file name from remote file path using basename
        file_name = Path(self.task_object.remote_file_path).name
        return file_name

    @log_function_entry_exit()
    def _read_metadata(self) -> None:
        """
        Internal method to read and parse the metadata from the task description file.
        Only reads metadata if the signature has been verified.
        """
        if not self.signature_verified:
            log_message(LoggingScope.ERROR, "ERROR", "Cannot read metadata: signature not verified for '%s'",
                        self.task_object.local_file_path)
            raise RuntimeError("Cannot read metadata: signature not verified")

        try:
            with open(self.task_object.local_file_path, "r") as file:
                self.raw_contents = file.read()
                self.metadata = json.loads(self.raw_contents)
            log_message(LoggingScope.DEBUG, "DEBUG", "Successfully read metadata from '%s'",
                        self.task_object.local_file_path)
        except json.JSONDecodeError as err:
            log_message(LoggingScope.ERROR, "ERROR", "Failed to parse JSON in task description file '%s': '%s'",
                        self.task_object.local_file_path, str(err))
            raise
        except Exception as err:
            log_message(LoggingScope.ERROR, "ERROR", "Failed to read task description file '%s': '%s'",
                        self.task_object.local_file_path, str(err))
            raise

    @log_function_entry_exit()
    def __str__(self) -> str:
        """Return a string representation of the EESSITaskDescription object."""
        return f"EESSITaskDescription({self.task_object.local_file_path}, verified={self.signature_verified})"
