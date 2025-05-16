from dataclasses import dataclass

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

    def __str__(self) -> str:
        """Return a string representation of the EESSITaskPayload object."""
        return f"EESSITaskPayload({self.payload_object.local_file_path}, verified={self.signature_verified})"
