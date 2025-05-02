import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import boto3
import configparser

from utils import log_function_entry_exit, log_message, LoggingScope
from remote_storage import RemoteStorageClient, DownloadMode


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
            # First check if we have local ETags
            try:
                local_file_etag = self._get_local_etag(self.local_file_path)
                local_sig_etag = self._get_local_etag(self.local_sig_path)

                if local_file_etag:
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Local file ETag: %s", local_file_etag)
                else:
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "No local file ETag found")
                if local_sig_etag:
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Local signature ETag: %s", local_sig_etag)
                else:
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "No local signature ETag found")

                # If we don't have local ETags, we need to download
                if not local_file_etag or not local_sig_etag:
                    should_download = True
                    log_message(LoggingScope.DOWNLOAD, 'INFO', "Missing local ETags, downloading %s", 
                              self.remote_file_path)
                else:
                    # Get remote ETags and compare
                    remote_file_etag = self.remote_client.get_metadata(self.remote_file_path)['ETag']
                    remote_sig_etag = self.remote_client.get_metadata(self.remote_sig_path)['ETag']
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Remote file ETag: %s", remote_file_etag)
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Remote signature ETag: %s", remote_sig_etag)

                    should_download = (
                        remote_file_etag != local_file_etag or
                        remote_sig_etag != local_sig_etag
                    )
                    if should_download:
                        if remote_file_etag != local_file_etag:
                            log_message(LoggingScope.DOWNLOAD, 'INFO', "File ETag changed from %s to %s", 
                                      local_file_etag, remote_file_etag)
                        if remote_sig_etag != local_sig_etag:
                            log_message(LoggingScope.DOWNLOAD, 'INFO', "Signature ETag changed from %s to %s", 
                                      local_sig_etag, remote_sig_etag)
                        log_message(LoggingScope.DOWNLOAD, 'INFO', "Remote files have changed, downloading %s", 
                                  self.remote_file_path)
                    else:
                        log_message(LoggingScope.DOWNLOAD, 'INFO', "Remote files unchanged, skipping download of %s", 
                                  self.remote_file_path)
            except Exception as etag_err:
                # If we get any error with ETags, we'll just download the files
                log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Error handling ETags, will download files: %s", str(etag_err))
                should_download = True
        else:  # CHECK_LOCAL
            should_download = (
                not self.local_file_path.exists() or
                not self.local_sig_path.exists()
            )
            if should_download:
                if not self.local_file_path.exists():
                    log_message(LoggingScope.DOWNLOAD, 'INFO', "Local file missing: %s", self.local_file_path)
                if not self.local_sig_path.exists():
                    log_message(LoggingScope.DOWNLOAD, 'INFO', "Local signature missing: %s", self.local_sig_path)
                log_message(LoggingScope.DOWNLOAD, 'INFO', "Local files missing, downloading %s", 
                          self.remote_file_path)
            else:
                log_message(LoggingScope.DOWNLOAD, 'INFO', "Local files exist, skipping download of %s", 
                          self.remote_file_path)

        if not should_download:
            return False

        # Ensure local directory exists
        self.local_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Download files
        try:
            # Download the main file first
            self.remote_client.download(self.remote_file_path, str(self.local_file_path))

            # Get and log the ETag of the downloaded file
            try:
                file_etag = self._get_local_etag(self.local_file_path)
                log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Downloaded %s with ETag: %s", 
                           self.remote_file_path, file_etag)
            except Exception as etag_err:
                log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Error getting ETag for %s: %s", 
                           self.remote_file_path, str(etag_err))

            # Try to download the signature file
            try:
                self.remote_client.download(self.remote_sig_path, str(self.local_sig_path))
                try:
                    sig_etag = self._get_local_etag(self.local_sig_path)
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Downloaded %s with ETag: %s", 
                               self.remote_sig_path, sig_etag)
                except Exception as etag_err:
                    log_message(LoggingScope.DOWNLOAD, 'DEBUG', "Error getting ETag for %s: %s", 
                               self.remote_sig_path, str(etag_err))
                log_message(LoggingScope.DOWNLOAD, 'INFO', "Successfully downloaded %s and its signature", 
                           self.remote_file_path)
            except Exception as sig_err:
                # Check if signatures are required
                if self.config['signatures'].getboolean('signatures_required', True):
                    # If signatures are required, clean up everything since we can't proceed
                    if self.local_file_path.exists():
                        self.local_file_path.unlink()
                    # Clean up etag files regardless of whether their data files exist
                    file_etag_path = self._get_etag_file_path(self.local_file_path)
                    if file_etag_path.exists():
                        file_etag_path.unlink()
                    sig_etag_path = self._get_etag_file_path(self.local_sig_path)
                    if sig_etag_path.exists():
                        sig_etag_path.unlink()
                    log_message(LoggingScope.ERROR, 'ERROR', "Failed to download required signature for %s: %s", 
                               self.remote_file_path, str(sig_err))
                    raise
                else:
                    # If signatures are optional, just clean up any partial signature files
                    if self.local_sig_path.exists():
                        self.local_sig_path.unlink()
                    sig_etag_path = self._get_etag_file_path(self.local_sig_path)
                    if sig_etag_path.exists():
                        sig_etag_path.unlink()
                    log_message(LoggingScope.DOWNLOAD, 'WARNING', "Failed to download optional signature for %s: %s", 
                               self.remote_file_path, str(sig_err))
                    log_message(LoggingScope.DOWNLOAD, 'INFO', "Successfully downloaded %s (signature optional)", 
                               self.remote_file_path)

            return True
        except Exception as err:
            # This catch block is only for errors in the main file download
            # Clean up partially downloaded files and their etags
            if self.local_file_path.exists():
                self.local_file_path.unlink()
            if self.local_sig_path.exists():
                self.local_sig_path.unlink()
            # Clean up etag files regardless of whether their data files exist
            file_etag_path = self._get_etag_file_path(self.local_file_path)
            if file_etag_path.exists():
                file_etag_path.unlink()
            sig_etag_path = self._get_etag_file_path(self.local_sig_path)
            if sig_etag_path.exists():
                sig_etag_path.unlink()
            log_message(LoggingScope.ERROR, 'ERROR', "Failed to download %s: %s", self.remote_file_path, str(err))
            raise

    def __str__(self) -> str:
        """Return a string representation of the EESSI data and signature object."""
        return f"EESSIDataAndSignatureObject({self.remote_file_path})"
