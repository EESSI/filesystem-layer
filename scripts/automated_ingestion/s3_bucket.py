import os
from pathlib import Path
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError
from utils import log_function_entry_exit, log_message, LoggingScope
from remote_storage import RemoteStorageClient


class EESSIS3Bucket(RemoteStorageClient):
    """EESSI-specific S3 bucket implementation of the RemoteStorageClient protocol."""

    @log_function_entry_exit()
    def __init__(self, config, bucket_name: str):
        """
        Initialize the EESSI S3 bucket.

        Args:
            config: Configuration object containing:
                   - aws.access_key_id: AWS access key ID (optional, can use AWS_ACCESS_KEY_ID env var)
                   - aws.secret_access_key: AWS secret access key (optional, can use AWS_SECRET_ACCESS_KEY env var)
                   - aws.endpoint_url: Custom endpoint URL for S3-compatible backends (optional)
                   - aws.verify: SSL verification setting (optional)
                         - True: Verify SSL certificates (default)
                         - False: Skip SSL certificate verification
                         - str: Path to CA bundle file
            bucket_name: Name of the S3 bucket to use
        """
        self.bucket = bucket_name

        # Get AWS credentials from environment or config
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID') or config.get('secrets', 'aws_access_key_id')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY') or config.get('secrets', 'aws_secret_access_key')

        # Configure boto3 client
        client_config = {}

        # Add endpoint URL if specified in config
        if config.has_option('aws', 'endpoint_url'):
            client_config['endpoint_url'] = config['aws']['endpoint_url']
            log_message(LoggingScope.DEBUG, 'DEBUG', "Using custom endpoint URL: %s", client_config['endpoint_url'])

        # Add SSL verification if specified in config
        if config.has_option('aws', 'verify'):
            verify = config['aws']['verify']
            if verify.lower() == 'false':
                client_config['verify'] = False
                log_message(LoggingScope.DEBUG, 'WARNING', "SSL verification disabled")
            elif verify.lower() == 'true':
                client_config['verify'] = True
            else:
                client_config['verify'] = verify  # Assume it's a path to CA bundle
                log_message(LoggingScope.DEBUG, 'DEBUG', "Using custom CA bundle: %s", verify)

        self.client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            **client_config
        )
        log_message(LoggingScope.DEBUG, 'INFO', "Initialized S3 client for bucket: %s", self.bucket)

    def list_objects_v2(self, **kwargs):
        """
        List objects in the bucket using the underlying boto3 client.

        Args:
            **kwargs: Additional arguments to pass to boto3.client.list_objects_v2

        Returns:
            Response from boto3.client.list_objects_v2
        """
        return self.client.list_objects_v2(Bucket=self.bucket, **kwargs)

    def download_file(self, key: str, filename: str) -> None:
        """
        Download a file from S3 to a local file.

        Args:
            key: The S3 key of the file to download
            filename: The local path where the file should be saved
        """
        self.client.download_file(self.bucket, key, filename)

    @log_function_entry_exit()
    def get_metadata(self, remote_path: str) -> Dict:
        """
        Get metadata about an S3 object.

        Args:
            remote_path: Path to the object in S3

        Returns:
            Dictionary containing object metadata, including 'ETag' key
        """
        try:
            log_message(LoggingScope.DEBUG, 'DEBUG', "Getting metadata for S3 object: %s", remote_path)
            response = self.client.head_object(Bucket=self.bucket, Key=remote_path)
            log_message(LoggingScope.DEBUG, 'DEBUG', "Retrieved metadata for %s: %s", remote_path, response)
            return response
        except ClientError as err:
            log_message(LoggingScope.ERROR, 'ERROR', "Failed to get metadata for %s: %s", remote_path, str(err))
            raise

    def _get_etag_file_path(self, local_path: str) -> Path:
        """Get the path to the .etag file for a given local file."""
        return Path(local_path).with_suffix('.etag')

    def _read_etag(self, local_path: str) -> Optional[str]:
        """Read the ETag from the .etag file if it exists."""
        etag_path = self._get_etag_file_path(local_path)
        if etag_path.exists():
            try:
                with open(etag_path, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                log_message(LoggingScope.DEBUG, 'WARNING', "Failed to read ETag file %s: %s", etag_path, str(e))
                return None
        return None

    def _write_etag(self, local_path: str, etag: str) -> None:
        """Write the ETag to the .etag file."""
        etag_path = self._get_etag_file_path(local_path)
        try:
            with open(etag_path, 'w') as f:
                f.write(etag)
            log_message(LoggingScope.DEBUG, 'DEBUG', "Wrote ETag to %s", etag_path)
        except Exception as e:
            log_message(LoggingScope.ERROR, 'ERROR', "Failed to write ETag file %s: %s", etag_path, str(e))
            # If we can't write the etag file, it's not critical
            # The file will just be downloaded again next time

    @log_function_entry_exit()
    def download(self, remote_path: str, local_path: str) -> None:
        """
        Download an S3 object to a local location and store its ETag.

        Args:
            remote_path: Path to the object in S3
            local_path: Local path where to save the file
        """
        try:
            log_message(LoggingScope.DOWNLOAD, 'INFO', "Downloading %s to %s", remote_path, local_path)
            self.client.download_file(Bucket=self.bucket, Key=remote_path, Filename=local_path)
            log_message(LoggingScope.DOWNLOAD, 'INFO', "Successfully downloaded %s to %s", remote_path, local_path)
        except ClientError as err:
            log_message(LoggingScope.ERROR, 'ERROR', "Failed to download %s: %s", remote_path, str(err))
            raise

        # Get metadata first to obtain the ETag
        metadata = self.get_metadata(remote_path)
        etag = metadata['ETag']

        # Store the ETag
        self._write_etag(local_path, etag)

    @log_function_entry_exit()
    def get_bucket_url(self) -> str:
        """
        Get the HTTPS URL for a bucket from an initialized boto3 client.
        Works with both AWS S3 and MinIO/S3-compatible services.
        """
        try:
            # Check if this is a custom endpoint (MinIO) or AWS S3
            endpoint_url = self.client.meta.endpoint_url

            if endpoint_url:
                # Custom endpoint (MinIO, DigitalOcean Spaces, etc.)
                # Most S3-compatible services use path-style URLs
                bucket_url = f"{endpoint_url}/{self.bucket}"

            else:
                # AWS S3 (no custom endpoint specified)
                region = self.client.meta.region_name or 'us-east-1'

                # AWS S3 virtual-hosted-style URLs
                if region == 'us-east-1':
                    bucket_url = f"https://{self.bucket}.s3.amazonaws.com"
                else:
                    bucket_url = f"https://{self.bucket}.s3.{region}.amazonaws.com"

            return bucket_url

        except Exception as err:
            log_message(LoggingScope.ERROR, 'ERROR', "Error getting bucket URL: %s", str(err))
            return None
