from enum import Enum
from typing import Protocol, runtime_checkable


class DownloadMode(Enum):
    """Enum defining different modes for downloading files."""
    FORCE = 'force'  # Always download and overwrite
    CHECK_REMOTE = 'check-remote'  # Download if remote files have changed
    CHECK_LOCAL = 'check-local'  # Download if files don't exist locally (default)


@runtime_checkable
class RemoteStorageClient(Protocol):
    """Protocol defining the interface for remote storage clients."""

    def get_metadata(self, remote_path: str) -> dict:
        """Get metadata about a remote object.

        Args:
            remote_path: Path to the object in remote storage

        Returns:
            Dictionary containing object metadata, including 'ETag' key
        """
        ...

    def download(self, remote_path: str, local_path: str) -> None:
        """Download a remote file to a local location.

        Args:
            remote_path: Path to the object in remote storage
            local_path: Local path where to save the file
        """
        ...
