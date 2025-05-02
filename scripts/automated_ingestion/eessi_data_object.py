import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

import boto3
import configparser

from utils import log_function_entry_exit, log_message, LoggingScope

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


@dataclass
class EESSIDataAndSignatureObject:
    """Class representing an EESSI data file and its signature in remote storage and locally."""

    # Configuration
    config: configparser.ConfigParser

    # Remote paths
    remote_file_path: str  # Path to data file in remote storage
    remote_sig_path: str  # Path to signature file in remote storage

    # Local paths
    local_file_path: Path  # Path to local data file
    local_sig_path: Path  # Path to local signature file

    # Remote storage client
    remote_client: RemoteStorageClient

    @log_function_entry_exit()
    def __init__(self, config: configparser.ConfigParser, remote_file_path: str, remote_client: RemoteStorageClient):
        """
        Initialize an EESSI data and signature object handler.

        Args:
            config: Configuration object containing remote storage and local directory information
            remote_file_path: Path to data file in remote storage
            remote_client: Remote storage client implementing the RemoteStorageClient protocol
        """
        self.config = config
        self.remote_file_path = remote_file_path
        sig_ext = config['signatures']['signature_file_extension']
        self.remote_sig_path = remote_file_path + sig_ext

        # Set up local paths
        local_dir = Path(config['paths']['download_dir'])
        # Use the full remote path structure, removing any leading slashes
        remote_path = remote_file_path.lstrip('/')
        self.local_file_path = local_dir.joinpath(remote_path)
        self.local_sig_path = local_dir.joinpath(remote_path + sig_ext)
        self.remote_client = remote_client

        log_message(LoggingScope.DEBUG, 'DEBUG', "Initialized EESSIDataAndSignatureObject for %s", remote_file_path)
        log_message(LoggingScope.DEBUG, 'DEBUG', "Local file path: %s", self.local_file_path)
        log_message(LoggingScope.DEBUG, 'DEBUG', "Local signature path: %s", self.local_sig_path)

    def _get_etag_file_path(self, local_path: Path) -> Path:
        """Get the path to the .etag file for a given local file."""
        return local_path.with_suffix('.etag')

    def _get_local_etag(self, local_path: Path) -> Optional[str]:
        """Get the ETag of a local file from its .etag file."""
        etag_path = self._get_etag_file_path(local_path)
        if etag_path.exists():
            try:
                with open(etag_path, 'r') as f:
                    return f.read().strip()
            except Exception as err:
                log_message(LoggingScope.DEBUG, 'WARNING', "Failed to read ETag file %s: %s", etag_path, str(err))
                return None
        return None

    def get_etags(self) -> tuple[Optional[str], Optional[str]]:
        """
        Get the ETags of both the data file and its signature.

        Returns:
            Tuple containing (data_file_etag, signature_file_etag)
        """
        return (
            self._get_local_etag(self.local_file_path),
            self._get_local_etag(self.local_sig_path)
        )

    @log_function_entry_exit()
    def download(self, mode: DownloadMode = DownloadMode.CHECK_LOCAL) -> bool:
        """
        Download data file and signature based on the specified mode.

        Args:
            mode: Download mode to use

        Returns:
            True if files were downloaded, False otherwise
        """
        if mode == DownloadMode.FORCE:
            should_download = True
            log_message(LoggingScope.DOWNLOAD, 'INFO', "Forcing download of %s", self.remote_file_path)
        elif mode == DownloadMode.CHECK_REMOTE:
            remote_file_etag = self.remote_client.get_metadata(self.remote_file_path)['ETag']
            remote_sig_etag = self.remote_client.get_metadata(self.remote_sig_path)['ETag']
            local_file_etag = self._get_local_etag(self.local_file_path)
            local_sig_etag = self._get_local_etag(self.local_sig_path)

            should_download = (
                remote_file_etag != local_file_etag or
                remote_sig_etag != local_sig_etag
            )
            if should_download:
                log_msg = "Remote files have changed, downloading %s"
                log_message(LoggingScope.DOWNLOAD, 'INFO', log_msg, self.remote_file_path)
            else:
                log_msg = "Remote files unchanged, skipping download of %s"
                log_message(LoggingScope.DOWNLOAD, 'DEBUG', log_msg, self.remote_file_path)
        else:  # CHECK_LOCAL
            should_download = (
                not self.local_file_path.exists() or
                not self.local_sig_path.exists()
            )
            if should_download:
                log_msg = "Local files missing, downloading %s"
                log_message(LoggingScope.DOWNLOAD, 'INFO', log_msg, self.remote_file_path)
            else:
                log_msg = "Local files exist, skipping download of %s"
                log_message(LoggingScope.DOWNLOAD, 'DEBUG', log_msg, self.remote_file_path)

        if not should_download:
            return False

        # Ensure local directory exists
        self.local_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Download files
        try:
            self.remote_client.download(self.remote_file_path, str(self.local_file_path))
            self.remote_client.download(self.remote_sig_path, str(self.local_sig_path))

            # Log the ETags of downloaded files
            file_etag = self._get_local_etag(self.local_file_path)
            sig_etag = self._get_local_etag(self.local_sig_path)
            log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Downloaded %s with ETag: %s", self.remote_file_path, file_etag)
            log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Downloaded %s with ETag: %s", self.remote_sig_path, sig_etag)

            log_msg = "Successfully downloaded %s and its signature"
            log_message(LoggingScope.DOWNLOAD, 'INFO', log_msg, self.remote_file_path)
            return True
        except Exception as err:
            # Clean up partially downloaded files
            if self.local_file_path.exists():
                self.local_file_path.unlink()
            if self.local_sig_path.exists():
                self.local_sig_path.unlink()
            log_message(LoggingScope.ERROR, 'ERROR', "Failed to download %s: %s", self.remote_file_path, str(err))
            raise

    def __str__(self) -> str:
        """Return a string representation of the EESSI data and signature object."""
        return f"EESSIDataAndSignatureObject({self.remote_file_path})"
