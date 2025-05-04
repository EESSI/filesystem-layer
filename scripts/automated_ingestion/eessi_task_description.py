import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

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

    def __str__(self) -> str:
        """Return a string representation of the EESSITaskDescription object."""
        return f"EESSITaskDescription({self.task_object.local_file_path}, verified={self.signature_verified})" 