import os
import logging
from typing import Any
from io import BytesIO
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger("storage")

class MinioStorage:
    """Enterprise S3-compatible client wrapper for MinIO storage."""
    
    _client = None
    BUCKET_NAME = "claimgpt"

    @classmethod
    def get_client(cls) -> Any:
        """Initialize and return a single-instance boto3 S3 client."""
        if cls._client is None:
            endpoint = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
            access_key = os.getenv("MINIO_ROOT_USER", "claimgpt")
            secret_key = os.getenv("MINIO_ROOT_PASSWORD", "claimgpt123")
            
            # Configure boto3 client with proper connection timeouts
            cls._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=5,
                    read_timeout=15,
                    retries={"max_attempts": 3}
                )
            )
            cls.ensure_bucket_exists()
        return cls._client

    @classmethod
    def ensure_bucket_exists(cls) -> None:
        """Verify that our primary bucket exists, or create it if missing."""
        client = boto3.client(
            "s3",
            endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
            aws_access_key_id=os.getenv("MINIO_ROOT_USER", "claimgpt"),
            aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "claimgpt123"),
            config=Config(signature_version="s3v4")
        )
        try:
            client.head_bucket(Bucket=cls.BUCKET_NAME)
            logger.info(f"[MINIO] Bucket '{cls.BUCKET_NAME}' already exists.")
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchBucket"):
                try:
                    client.create_bucket(Bucket=cls.BUCKET_NAME)
                    logger.info(f"[MINIO] Created bucket '{cls.BUCKET_NAME}' successfully.")
                except Exception as ex:
                    logger.error(f"[MINIO] Failed to create bucket '{cls.BUCKET_NAME}': {ex}")
            else:
                logger.error(f"[MINIO] Error checking bucket '{cls.BUCKET_NAME}': {e}")

    @classmethod
    def upload_file(cls, minio_key: str, file_path_or_bytes: Any) -> str:
        """Upload a file from disk or bytes to MinIO and return its MinIO URI."""
        client = cls.get_client()
        try:
            if isinstance(file_path_or_bytes, bytes):
                client.upload_fileobj(
                    BytesIO(file_path_or_bytes),
                    cls.BUCKET_NAME,
                    minio_key
                )
            else:
                client.upload_file(
                    str(file_path_or_bytes),
                    cls.BUCKET_NAME,
                    minio_key
                )
            minio_uri = f"s3://{cls.BUCKET_NAME}/{minio_key}"
            logger.info(f"[MINIO] Successfully uploaded to: {minio_uri}")
            return minio_uri
        except Exception as e:
            logger.exception(f"[MINIO] Failed to upload object '{minio_key}': {e}")
            raise

    @classmethod
    def download_file(cls, minio_uri: str, local_dest_path: str) -> None:
        """Download an object from MinIO using its URI to a local destination."""
        client = cls.get_client()
        try:
            if not minio_uri.startswith("s3://"):
                raise ValueError(f"Invalid MinIO URI: {minio_uri}")
            
            # Parse s3://bucket/key
            path_parts = minio_uri[5:].split("/", 1)
            bucket = path_parts[0]
            minio_key = path_parts[1]
            
            client.download_file(bucket, minio_key, str(local_dest_path))
            logger.info(f"[MINIO] Successfully downloaded {minio_uri} -> {local_dest_path}")
        except Exception as e:
            logger.exception(f"[MINIO] Failed to download object '{minio_uri}': {e}")
            raise

    @classmethod
    def download_to_temp(cls, minio_uri: str) -> str:
        """Download an object from MinIO to a temporary file and return its path.
        
        CRITICAL: The caller is responsible for deleting the temp file after use!
        """
        import tempfile
        client = cls.get_client()
        try:
            if not minio_uri.startswith("s3://"):
                raise ValueError(f"Invalid MinIO URI: {minio_uri}")
            
            path_parts = minio_uri[5:].split("/", 1)
            bucket = path_parts[0]
            minio_key = path_parts[1]
            
            # Preserve file extension
            suffix = os.path.splitext(minio_key)[1] or ".bin"
            
            # Create a secure temp file (not closed/deleted automatically so caller can read it)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            temp_path = temp_file.name
            temp_file.close()
            
            client.download_file(bucket, minio_key, temp_path)
            logger.info(f"[MINIO] Downloaded to temporary file: {temp_path}")
            return temp_path
        except Exception as e:
            logger.exception(f"[MINIO] Failed to download object to temp '{minio_uri}': {e}")
            raise
