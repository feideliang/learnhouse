import logging
from typing import Literal, Optional
import boto3
import botocore.config
from botocore.exceptions import ClientError
import os
from fastapi import HTTPException, UploadFile
from config.config import get_learnhouse_config
from src.security.file_validation import validate_upload

logger = logging.getLogger(__name__)


def ensure_directory_exists(directory: str):
    if not os.path.exists(directory):
        os.makedirs(directory)


async def upload_file(
    file: UploadFile,
    directory: str,
    type_of_dir: Literal["orgs", "users"],
    uuid: str,
    allowed_types: list[str],
    filename_prefix: str,
    max_size: Optional[int] = None,
) -> str:
    """
    Secure file upload with validation.
    
    Args:
        file: The uploaded file
        directory: Target directory (e.g., "logos", "avatars")
        type_of_dir: "orgs" or "users"
        uuid: Organization or user UUID
        allowed_types: List of allowed file types ('image', 'video', 'document')
        filename_prefix: Prefix for the generated filename
        max_size: Maximum file size in bytes (optional)
        
    Returns:
        The saved filename
    """
    from uuid import uuid4
    from src.security.file_validation import get_safe_filename
    
    # Validate the file
    _, content = validate_upload(file, allowed_types, max_size)
    
    # Generate safe filename
    filename = get_safe_filename(file.filename, f"{uuid4()}_{filename_prefix}")
    
    # Save the file
    await upload_content(
        directory=directory,
        type_of_dir=type_of_dir,
        uuid=uuid,
        file_binary=content,
        file_and_format=filename,
        allowed_formats=None,  # Already validated
    )
    
    return filename


async def upload_content(
    directory: str,
    type_of_dir: Literal["orgs", "users"],
    uuid: str,  # org_uuid or user_uuid
    file_binary: bytes,
    file_and_format: str,
    allowed_formats: Optional[list[str]] = None,
):
    # Get Learnhouse Config
    learnhouse_config = get_learnhouse_config()

    file_format = file_and_format.split(".")[-1].strip().lower()

    # Get content delivery method
    content_delivery = learnhouse_config.hosting_config.content_delivery.type

    # Check if format file is allowed
    if allowed_formats:
        if file_format not in allowed_formats:
            raise HTTPException(
                status_code=400,
                detail=f"File format {file_format} not allowed",
            )

    ensure_directory_exists(f"content/{type_of_dir}/{uuid}/{directory}")

    if content_delivery == "filesystem":
        # upload file to server
        with open(
            f"content/{type_of_dir}/{uuid}/{directory}/{file_and_format}",
            "wb",
        ) as f:
            f.write(file_binary)
            f.close()

    elif content_delivery == "s3api":
        s3_config = learnhouse_config.hosting_config.content_delivery.s3api
        upload_timeout = int(os.environ.get("LEARNHOUSE_UPLOAD_TIMEOUT", "1800"))
        kwargs = {
            "endpoint_url": s3_config.endpoint_url,
            "config": botocore.config.Config(connect_timeout=10, read_timeout=upload_timeout, retries={"max_attempts": 2}),
        }
        if s3_config.access_key:
            kwargs["aws_access_key_id"] = s3_config.access_key
        if s3_config.secret_key:
            kwargs["aws_secret_access_key"] = s3_config.secret_key
        s3 = boto3.client("s3", **kwargs)

        bucket_name = learnhouse_config.hosting_config.content_delivery.s3api.bucket_name or "learnhouse-media"
        local_path = f"content/{type_of_dir}/{uuid}/{directory}/{file_and_format}"
        # S3 key must NOT include 'content/' prefix — stream/content endpoints use keys without it
        s3_key = f"{type_of_dir}/{uuid}/{directory}/{file_and_format}"

        # Determine ContentType from file extension for proper MIME type in S3
        content_type = None
        ext = file_format.lower()
        mime_types = {
            "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
            "pdf": "application/pdf",
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
            "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
        }
        if ext in mime_types:
            content_type = mime_types[ext]

        # Write to local temp file for S3 upload
        with open(local_path, "wb") as f:
            f.write(file_binary)

        try:
            upload_args = {"Filename": local_path, "Bucket": bucket_name, "Key": s3_key}
            if content_type:
                upload_args["ExtraArgs"] = {"ContentType": content_type}
            s3.upload_file(**upload_args)
            s3.head_object(Bucket=bucket_name, Key=s3_key)
            logger.debug("S3 upload successful: %s", s3_key)
        except ClientError as e:
            logger.error("S3 upload failed: %s", e)
            raise HTTPException(status_code=500, detail="File upload to storage failed")
        finally:
            # Clean up local temp file after S3 upload
            try:
                os.remove(local_path)
            except OSError as cleanup_err:
                logger.error("Failed to clean up temp file %s: %s", local_path, cleanup_err)
