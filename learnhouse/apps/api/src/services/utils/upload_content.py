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

# Chunk size for streaming writes on the filesystem backend.
_STREAM_CHUNK = 1024 * 1024  # 1MB


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

    Validates the file without reading the whole body into memory, then streams
    the upload directly to the configured content delivery backend.
    """
    from uuid import uuid4
    from src.security.file_validation import get_safe_filename

    # Validate the file (streaming — does not load the full body into RAM).
    validate_upload(file, allowed_types, max_size)

    # Generate safe filename
    filename = get_safe_filename(file.filename, f"{uuid4()}_{filename_prefix}")

    # Save the file by streaming the UploadFile onwards.
    await upload_content(
        directory=directory,
        type_of_dir=type_of_dir,
        uuid=uuid,
        file=file,
        file_and_format=filename,
        allowed_formats=None,  # Already validated
    )

    return filename


async def upload_content(
    directory: str,
    type_of_dir: Literal["orgs", "users"],
    uuid: str,  # org_uuid or user_uuid
    file_and_format: str,
    allowed_formats: Optional[list[str]] = None,
    file: Optional[UploadFile] = None,
    file_binary: Optional[bytes] = None,
):
    """Persist the given upload to the configured content delivery backend.

    Either ``file`` (preferred, streaming) or ``file_binary`` (legacy bytes
    payload) must be supplied.
    """
    if file is None and file_binary is None:
        raise ValueError("upload_content requires either file or file_binary")

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
        target = f"content/{type_of_dir}/{uuid}/{directory}/{file_and_format}"
        with open(target, "wb") as f:
            if file is not None:
                file.file.seek(0)
                while True:
                    chunk = file.file.read(_STREAM_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                file.file.seek(0)
            else:
                f.write(file_binary)

    elif content_delivery == "s3api":
        s3_config = learnhouse_config.hosting_config.content_delivery.s3api
        upload_timeout = int(os.environ.get("LEARNHOUSE_UPLOAD_TIMEOUT", "1800"))
        kwargs = {
            "endpoint_url": s3_config.endpoint_url,
            "config": botocore.config.Config(connect_timeout=10, read_timeout=upload_timeout, retries={"max_attempts": 2}),
        }
        if getattr(s3_config, "access_key", None):
            kwargs["aws_access_key_id"] = s3_config.access_key
        if getattr(s3_config, "secret_key", None):
            kwargs["aws_secret_access_key"] = s3_config.secret_key
        s3 = boto3.client("s3", **kwargs)

        bucket_name = learnhouse_config.hosting_config.content_delivery.s3api.bucket_name or "learnhouse-media"
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

        extra_args = {"ContentType": content_type} if content_type else {}

        try:
            if file is not None:
                # Stream directly from the SpooledTemporaryFile — boto3 will
                # transparently do multipart upload for large payloads.
                file.file.seek(0)
                s3.upload_fileobj(
                    file.file,
                    bucket_name,
                    s3_key,
                    ExtraArgs=extra_args,
                )
                # Leave the pointer at 0 so downstream code (e.g. metadata
                # collection) can re-read if needed.
                file.file.seek(0)
            else:
                import io
                s3.upload_fileobj(
                    io.BytesIO(file_binary),
                    bucket_name,
                    s3_key,
                    ExtraArgs=extra_args,
                )
            s3.head_object(Bucket=bucket_name, Key=s3_key)
            logger.debug("S3 upload successful: %s", s3_key)
        except ClientError as e:
            logger.error("S3 upload failed: %s", e)
            raise HTTPException(status_code=500, detail="File upload to storage failed")
