import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from eessi_data_object import EESSIDataAndSignatureObject
from utils import log_function_entry_exit, log_message, LoggingScope
from remote_storage import DownloadMode


@dataclass
class EESSITaskDescription:
    """Class representing an EESSI task to be performed, including its metadata and associated data files."""

    # The EESSI data and signature object associated with this task
    task_object: EESSIDataAndSignatureObject

    # Whether the signature was successfully verified
    signature_verified: bool = False

    # Metadata from the task description file
    metadata: Dict[str, Any] = None

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

        # Verify signature and set initial state
        self.signature_verified = self.task_object.verify_signature()
        
        # Try to read metadata (will only succeed if signature is verified)
        try:
            self._read_metadata()
        except RuntimeError:
            # Expected if signature is not verified yet
            pass

        # TODO: Process the task file contents
        # check if the task file contains a task field and add that to self
        if 'task' in self.metadata:
            self.task = self.metadata['task']
        else:
            self.task = None

    @log_function_entry_exit()
    def _read_metadata(self) -> None:
        """
        Internal method to read and parse the metadata from the task description file.
        Only reads metadata if the signature has been verified.
        """
        if not self.signature_verified:
            log_message(LoggingScope.ERROR, 'ERROR', "Cannot read metadata: signature not verified for %s", 
                       self.task_object.local_file_path)
            raise RuntimeError("Cannot read metadata: signature not verified")

        try:
            with open(self.task_object.local_file_path, 'r') as f:
                self.metadata = json.load(f)
            log_message(LoggingScope.DEBUG, 'DEBUG', "Successfully read metadata from %s", self.task_object.local_file_path)
        except json.JSONDecodeError as e:
            log_message(LoggingScope.ERROR, 'ERROR', "Failed to parse JSON in task description file %s: %s", 
                       self.task_object.local_file_path, str(e))
            raise
        except Exception as e:
            log_message(LoggingScope.ERROR, 'ERROR', "Failed to read task description file %s: %s", 
                       self.task_object.local_file_path, str(e))
            raise

    def get_metadata_file_components(self) -> Tuple[str, str, str, str, str, str]:
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
        # from file_name_without_suffix determine VERSION (2nd element), COMPONENT (3rd element), OS (4th element),
        #  ARCHITECTURE (5th to second last elements) and TIMESTAMP (last element)
        components = file_name_without_suffix.split('-')
        version = components[1]
        component = components[2]
        os = components[3]
        architecture = '-'.join(components[4:-1])
        timestamp = components[-1]
        return version, component, os, architecture, timestamp, suffix

    def __str__(self) -> str:
        """Return a string representation of the EESSITaskDescription object."""
        return f"EESSITaskDescription({self.task_object.local_file_path}, verified={self.signature_verified})" 