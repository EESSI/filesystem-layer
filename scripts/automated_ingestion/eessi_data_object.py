from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import configparser
import subprocess

from eessi_logging import log_function_entry_exit, log_message, LoggingScope
from eessi_remote_storage_client import DownloadMode, EESSIRemoteStorageClient


@dataclass
class EESSIDataAndSignatureObject:
    """Class representing an EESSI data file and its signature in remote storage and locally."""

    # configuration
    config: configparser.ConfigParser

    # remote paths
    remote_file_path: str  # path to data file in remote storage
    remote_sig_path: str  # path to signature file in remote storage

    # local paths
    local_file_path: Path  # path to local data file
    local_sig_path: Path  # path to local signature file

    # remote storage client
    remote_client: EESSIRemoteStorageClient

    @log_function_entry_exit()
    def __init__(
        self,
        config: configparser.ConfigParser,
        remote_file_path: str,
        remote_client: EESSIRemoteStorageClient,
    ):
        """
        Initialize an EESSI data and signature object handler.

        Args:
            config: configuration object containing remote storage and local directory information
            remote_file_path: path to data file in remote storage
            remote_client: remote storage client implementing the EESSIRemoteStorageClient protocol
        """
        self.config = config
        self.remote_file_path = remote_file_path
        sig_ext = config["signatures"]["signature_file_extension"]
        self.remote_sig_path = remote_file_path + sig_ext

        # set up local paths
        local_dir = Path(config["paths"]["download_dir"])
        # use the full remote path structure, removing any leading slashes
        remote_path = remote_file_path.lstrip("/")
        self.local_file_path = local_dir.joinpath(remote_path)
        self.local_sig_path = local_dir.joinpath(remote_path + sig_ext)
        self.remote_client = remote_client

        log_message(LoggingScope.DEBUG, "DEBUG", "Initialized EESSIDataAndSignatureObject for '%s'", remote_file_path)
        log_message(LoggingScope.DEBUG, "DEBUG", "Local file path: '%s'", self.local_file_path)
        log_message(LoggingScope.DEBUG, "DEBUG", "Local signature path: '%s'", self.local_sig_path)

    @log_function_entry_exit()
    def _get_etag_file_path(self, local_path: Path) -> Path:
        """Get the path to the .etag file for a given local file."""
        return local_path.with_suffix(".etag")

    @log_function_entry_exit()
    def _get_local_etag(self, local_path: Path) -> Optional[str]:
        """Get the ETag of a local file from its .etag file."""
        etag_path = self._get_etag_file_path(local_path)
        if etag_path.exists():
            try:
                with open(etag_path, "r") as f:
                    return f.read().strip()
            except Exception as err:
                log_message(LoggingScope.DEBUG, "WARNING", "Failed to read ETag file '%s': '%s'", etag_path, str(err))
                return None
        return None

    @log_function_entry_exit()
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
    def verify_signature(self) -> bool:
        """
        Verify the signature of the data file using the corresponding signature file.

        Returns:
            bool: True if the signature is valid or if signatures are not required, False otherwise
        """
        # check if signature file exists
        if not self.local_sig_path.exists():
            log_message(LoggingScope.VERIFICATION, "WARNING", "Signature file '%s' is missing",
                        self.local_sig_path)

            # if signatures are required, return failure
            if self.config["signatures"].getboolean("signatures_required", True):
                log_message(LoggingScope.ERROR, "ERROR", "Signature file '%s' is missing and signatures are required",
                            self.local_sig_path)
                return False
            else:
                log_message(LoggingScope.VERIFICATION, "INFO",
                            "Signature file '%s' is missing, but signatures are not required",
                            self.local_sig_path)
                return True

        # if signatures are provided, we should always verify them, regardless of the signatures_required setting
        verify_runenv = self.config["signatures"]["signature_verification_runenv"].split()
        verify_script = self.config["signatures"]["signature_verification_script"]
        allowed_signers_file = self.config["signatures"]["allowed_signers_file"]

        # check if verification tools exist
        if not Path(verify_script).exists():
            log_message(LoggingScope.ERROR, "ERROR",
                        "Unable to verify signature: verification script '%s' does not exist", verify_script)
            return False

        if not Path(allowed_signers_file).exists():
            log_message(LoggingScope.ERROR, "ERROR",
                        "Unable to verify signature: allowed signers file '%s' does not exist", allowed_signers_file)
            return False

        # run the verification command with named parameters
        cmd = verify_runenv + [
            verify_script,
            "--verify",
            "--allowed-signers-file", allowed_signers_file,
            "--file", str(self.local_file_path),
            "--signature-file", str(self.local_sig_path)
        ]
        log_message(LoggingScope.VERIFICATION, "INFO", "Running command: '%s'", " ".join(cmd))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                log_message(LoggingScope.VERIFICATION, "INFO",
                            "Successfully verified signature for '%s'", self.local_file_path)
                log_message(LoggingScope.VERIFICATION, "DEBUG", "  stdout: '%s'", result.stdout)
                log_message(LoggingScope.VERIFICATION, "DEBUG", "  stderr: '%s'", result.stderr)
                return True
            else:
                log_message(LoggingScope.ERROR, "ERROR",
                            "Signature verification failed for '%s'", self.local_file_path)
                log_message(LoggingScope.ERROR, "ERROR", "  stdout: '%s'", result.stdout)
                log_message(LoggingScope.ERROR, "ERROR", "  stderr: '%s'", result.stderr)
                return False
        except Exception as err:
            log_message(LoggingScope.ERROR, "ERROR",
                        "Error during signature verification for '%s': '%s'",
                        self.local_file_path, str(err))
            return False

    @log_function_entry_exit()
    def download(self, mode: DownloadMode = DownloadMode.CHECK_REMOTE) -> bool:
        """
        Download data file and signature based on the specified mode.

        Args:
            mode: Download mode to use

        Returns:
            True if files were downloaded, False otherwise
        """
        # if mode is FORCE, we always download regardless of local or remote state
        if mode == DownloadMode.FORCE:
            should_download = True
            log_message(LoggingScope.DOWNLOAD, "INFO", "Forcing download of '%s'", self.remote_file_path)
        # for CHECK_REMOTE mode, check if we can optimize
        elif mode == DownloadMode.CHECK_REMOTE:
            # optimization: check if local files exist first
            local_files_exist = (
                self.local_file_path.exists() and
                self.local_sig_path.exists()
            )

            # if files don't exist locally, we can skip ETag checks
            if not local_files_exist:
                log_message(LoggingScope.DOWNLOAD, "INFO",
                            "Local files missing, skipping ETag checks and downloading '%s'",
                            self.remote_file_path)
                should_download = True
            else:
                # first check if we have local ETags
                try:
                    local_file_etag = self._get_local_etag(self.local_file_path)
                    local_sig_etag = self._get_local_etag(self.local_sig_path)

                    if local_file_etag:
                        log_message(LoggingScope.DOWNLOAD, "DEBUG", "Local file ETag: '%s'", local_file_etag)
                    else:
                        log_message(LoggingScope.DOWNLOAD, "DEBUG", "No local file ETag found")
                    if local_sig_etag:
                        log_message(LoggingScope.DOWNLOAD, "DEBUG", "Local signature ETag: '%s'", local_sig_etag)
                    else:
                        log_message(LoggingScope.DOWNLOAD, "DEBUG", "No local signature ETag found")

                    # if we don't have local ETags, we need to download
                    if not local_file_etag or not local_sig_etag:
                        should_download = True
                        log_message(LoggingScope.DOWNLOAD, "INFO", "Missing local ETags, downloading '%s'",
                                    self.remote_file_path)
                    else:
                        # get remote ETags and compare
                        remote_file_etag = self.remote_client.get_metadata(self.remote_file_path)["ETag"]
                        remote_sig_etag = self.remote_client.get_metadata(self.remote_sig_path)["ETag"]
                        log_message(LoggingScope.DOWNLOAD, "DEBUG", "Remote file ETag: '%s'", remote_file_etag)
                        log_message(LoggingScope.DOWNLOAD, "DEBUG", "Remote signature ETag: '%s'", remote_sig_etag)

                        should_download = (
                            remote_file_etag != local_file_etag or
                            remote_sig_etag != local_sig_etag
                        )
                        if should_download:
                            if remote_file_etag != local_file_etag:
                                log_message(LoggingScope.DOWNLOAD, "INFO", "File ETag changed from '%s' to '%s'",
                                            local_file_etag, remote_file_etag)
                            if remote_sig_etag != local_sig_etag:
                                log_message(LoggingScope.DOWNLOAD, "INFO", "Signature ETag changed from '%s' to '%s'",
                                            local_sig_etag, remote_sig_etag)
                            log_message(LoggingScope.DOWNLOAD, "INFO", "Remote files have changed, downloading '%s'",
                                        self.remote_file_path)
                        else:
                            log_message(LoggingScope.DOWNLOAD, "INFO",
                                        "Remote files unchanged, skipping download of '%s'",
                                        self.remote_file_path)
                except Exception as etag_err:
                    # if we get any error with ETags, we'll just download the files
                    log_message(LoggingScope.DOWNLOAD, "DEBUG", "Error handling ETags, will download files: '%s'",
                                str(etag_err))
                    should_download = True
        else:  # check_local
            should_download = (
                not self.local_file_path.exists() or
                not self.local_sig_path.exists()
            )
            if should_download:
                if not self.local_file_path.exists():
                    log_message(LoggingScope.DOWNLOAD, "INFO", "Local file missing: '%s'", self.local_file_path)
                if not self.local_sig_path.exists():
                    log_message(LoggingScope.DOWNLOAD, "INFO", "Local signature missing: '%s'", self.local_sig_path)
                log_message(LoggingScope.DOWNLOAD, "INFO", "Local files missing, downloading '%s'",
                            self.remote_file_path)
            else:
                log_message(LoggingScope.DOWNLOAD, "INFO", "Local files exist, skipping download of '%s'",
                            self.remote_file_path)

        if not should_download:
            return False

        # ensure local directory exists
        self.local_file_path.parent.mkdir(parents=True, exist_ok=True)

        # download files
        try:
            # download the main file first
            self.remote_client.download(self.remote_file_path, str(self.local_file_path))

            # get and log the ETag of the downloaded file
            try:
                file_etag = self._get_local_etag(self.local_file_path)
                log_message(LoggingScope.DOWNLOAD, "DEBUG", "Downloaded '%s' with ETag: '%s'",
                            self.remote_file_path, file_etag)
            except Exception as etag_err:
                log_message(LoggingScope.DOWNLOAD, "DEBUG", "Error getting ETag for '%s': '%s'",
                            self.remote_file_path, str(etag_err))

            # try to download the signature file
            try:
                self.remote_client.download(self.remote_sig_path, str(self.local_sig_path))
                try:
                    sig_etag = self._get_local_etag(self.local_sig_path)
                    log_message(LoggingScope.DOWNLOAD, "DEBUG", "Downloaded '%s' with ETag: '%s'",
                                self.remote_sig_path, sig_etag)
                except Exception as etag_err:
                    log_message(LoggingScope.DOWNLOAD, "DEBUG", "Error getting ETag for '%s': '%s'",
                                self.remote_sig_path, str(etag_err))
                log_message(LoggingScope.DOWNLOAD, "INFO", "Successfully downloaded '%s' and its signature",
                            self.remote_file_path)
            except Exception as sig_err:
                # check if signatures are required
                if self.config["signatures"].getboolean("signatures_required", True):
                    # if signatures are required, clean up everything since we can't proceed
                    if self.local_file_path.exists():
                        self.local_file_path.unlink()
                    # clean up etag files regardless of whether their data files exist
                    file_etag_path = self._get_etag_file_path(self.local_file_path)
                    if file_etag_path.exists():
                        file_etag_path.unlink()
                    sig_etag_path = self._get_etag_file_path(self.local_sig_path)
                    if sig_etag_path.exists():
                        sig_etag_path.unlink()
                    log_message(LoggingScope.ERROR, "ERROR", "Failed to download required signature for '%s': '%s'",
                                self.remote_file_path, str(sig_err))
                    raise
                else:
                    # if signatures are optional, just clean up any partial signature files
                    if self.local_sig_path.exists():
                        self.local_sig_path.unlink()
                    sig_etag_path = self._get_etag_file_path(self.local_sig_path)
                    if sig_etag_path.exists():
                        sig_etag_path.unlink()
                    log_message(LoggingScope.DOWNLOAD, "WARNING",
                                "Failed to download optional signature for '%s': '%s'",
                                self.remote_file_path, str(sig_err))
                    log_message(LoggingScope.DOWNLOAD, "INFO",
                                "Successfully downloaded '%s' (signature optional)",
                                self.remote_file_path)

            return True
        except Exception as err:
            # this catch block is only for errors in the main file download
            # clean up partially downloaded files and their etags
            if self.local_file_path.exists():
                self.local_file_path.unlink()
            if self.local_sig_path.exists():
                self.local_sig_path.unlink()
            # clean up etag files regardless of whether their data files exist
            file_etag_path = self._get_etag_file_path(self.local_file_path)
            if file_etag_path.exists():
                file_etag_path.unlink()
            sig_etag_path = self._get_etag_file_path(self.local_sig_path)
            if sig_etag_path.exists():
                sig_etag_path.unlink()
            log_message(LoggingScope.ERROR, "ERROR", "Failed to download '%s': '%s'", self.remote_file_path, str(err))
            raise

    @log_function_entry_exit()
    def get_url(self) -> str:
        """Get the URL of the data file."""
        return f"https://{self.remote_client.bucket}.s3.amazonaws.com/{self.remote_file_path}"

    def __str__(self) -> str:
        """Return a string representation of the EESSI data and signature object."""
        return f"EESSIDataAndSignatureObject({self.remote_file_path})"
