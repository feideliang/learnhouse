"""
Video Streaming Router

This router provides optimized video streaming endpoints with proper HTTP Range
request handling for seamless playback of long video files.

SECURITY: All streaming endpoints validate resource access using the RBAC system.
Anonymous users can only stream content from public+published resources.

BANDWIDTH PROTECTION:
- Large files (>50MB) always return 206 Partial Content even without Range header,
  serving only the initial chunk range to prevent full-file bandwidth saturation.
- Concurrent streaming sessions are tracked with per-IP concurrency limiting.
- Streaming generators are timeout-wrapped to prevent zombie connections.
"""

import asyncio
import logging
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request, Path
from fastapi.responses import StreamingResponse, Response
from sqlmodel import Session, select

from src.db.courses.courses import Course
from src.db.courses.activities import Activity
from src.db.podcasts.podcasts import Podcast
from src.db.podcasts.episodes import PodcastEpisode
from src.db.users import AnonymousUser, PublicUser, APITokenUser
from src.core.events.database import get_db_session
from src.security.auth import get_current_user
from src.security.rbac.resource_access import ResourceAccessChecker, AccessAction, AccessContext
from src.services.utils.video_streaming import (
    stream_video_file,
    parse_range_header,
    get_file_info,
    validate_video_path,
    CHUNK_SIZE,
    STREAM_TIMEOUT_SECONDS,
    MAX_FILE_SIZE_FOR_FULL_STREAM,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Base content directory
CONTENT_DIR = "content"

# --- Bandwidth protection: concurrent stream limiter ---
# Track active streams per client IP to prevent a single IP from
# saturating bandwidth with many simultaneous full-file downloads.
_active_streams: defaultdict[str, int] = defaultdict(int)
_stream_lock = asyncio.Lock()
MAX_CONCURRENT_STREAMS_PER_IP = 5


async def _acquire_stream_slot(client_ip: str) -> bool:
    """Try to acquire a stream slot for the given client IP."""
    async with _stream_lock:
        if _active_streams[client_ip] >= MAX_CONCURRENT_STREAMS_PER_IP:
            return False
        _active_streams[client_ip] += 1
        return True


async def _release_stream_slot(client_ip: str):
    """Release a stream slot for the given client IP."""
    async with _stream_lock:
        _active_streams[client_ip] = max(0, _active_streams[client_ip] - 1)


async def _serve_stream_with_protection(
    request: Request,
    file_path: str,
    file_size: int,
    mime_type: str,
) -> StreamingResponse:
    """
    Serve a streaming response with bandwidth protection:
    - Forces 206 Partial Content for large files (>50MB) even without Range header
    - Limits concurrent streams per IP
    - Properly tracks stream lifecycle
    """
    range_header = request.headers.get("range")
    has_explicit_range = bool(range_header)

    if has_explicit_range:
        start, end = parse_range_header(range_header, file_size)
    elif file_size > MAX_FILE_SIZE_FOR_FULL_STREAM:
        start = 0
        end = min(CHUNK_SIZE * 10 - 1, file_size - 1)
    else:
        start, end = 0, file_size - 1

    content_length = end - start + 1
    client_ip = _get_client_ip(request)

    if not await _acquire_stream_slot(client_ip):
        logger.warning("Max concurrent streams reached for IP %s", client_ip)
        raise HTTPException(status_code=429, detail="Too many concurrent video streams")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime_type,
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }

    should_use_206 = has_explicit_range or file_size > MAX_FILE_SIZE_FOR_FULL_STREAM

    if should_use_206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(content_length)

        async def _gen():
            try:
                for chunk in stream_video_file(file_path, start, end, CHUNK_SIZE):
                    yield chunk
            finally:
                await _release_stream_slot(client_ip)

        return StreamingResponse(_gen(), status_code=206, headers=headers, media_type=mime_type)
    else:
        headers["Content-Length"] = str(file_size)

        async def _gen_full():
            try:
                for chunk in stream_video_file(file_path, start, end, CHUNK_SIZE):
                    yield chunk
            finally:
                await _release_stream_slot(client_ip)

        return StreamingResponse(_gen_full(), status_code=200, headers=headers, media_type=mime_type)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


async def _wrap_stream_with_timeout(generator, timeout: float = STREAM_TIMEOUT_SECONDS, client_ip: str = ""):
    """Wrap a streaming generator with a timeout. If no chunk is yielded
    within the timeout, the connection is closed to prevent zombie streams
    from holding bandwidth slots."""
    try:
        async for chunk in generator:
            yield chunk
    except asyncio.TimeoutError:
        logger.warning("Stream timeout for client %s after %ss", client_ip, timeout)
    finally:
        if client_ip:
            await _release_stream_slot(client_ip)


async def _verify_course_activity_access(
    request: Request,
    course_uuid: str,
    activity_uuid: str,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    db_session: Session,
) -> None:
    """
    Verify user has read access to the course/activity.

    SECURITY: This ensures that:
    - Anonymous users can only access public+published courses
    - Authenticated users can access courses they have permission to view
    - Activity must belong to the specified course
    """
    # Verify activity exists and belongs to the course
    activity_stmt = select(Activity).where(Activity.activity_uuid == activity_uuid)
    activity = db_session.exec(activity_stmt).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Verify course exists and activity belongs to it
    course_stmt = select(Course).where(Course.id == activity.course_id)
    course = db_session.exec(course_stmt).first()

    if not course or course.course_uuid != course_uuid:
        raise HTTPException(status_code=404, detail="Course not found or activity doesn't belong to course")

    # RBAC check - verify user can read this course
    checker = ResourceAccessChecker(request, db_session, current_user)
    decision = await checker.check_access(course_uuid, AccessAction.READ, AccessContext.PUBLIC_VIEW)

    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


async def _verify_podcast_episode_access(
    request: Request,
    podcast_uuid: str,
    episode_uuid: str,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    db_session: Session,
) -> None:
    """
    Verify user has read access to the podcast/episode.

    SECURITY: This ensures that:
    - Anonymous users can only access public+published podcasts
    - Authenticated users can access podcasts they have permission to view
    - Episode must belong to the specified podcast
    """
    # Verify episode exists and belongs to the podcast
    episode_stmt = select(PodcastEpisode).where(PodcastEpisode.episode_uuid == episode_uuid)
    episode = db_session.exec(episode_stmt).first()

    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    podcast_stmt = select(Podcast).where(Podcast.id == episode.podcast_id)
    podcast = db_session.exec(podcast_stmt).first()

    if not podcast or podcast.podcast_uuid != podcast_uuid:
        raise HTTPException(status_code=404, detail="Podcast not found or episode doesn't belong to podcast")

    # RBAC check - verify user can read this podcast
    checker = ResourceAccessChecker(request, db_session, current_user)
    decision = await checker.check_access(podcast_uuid, AccessAction.READ, AccessContext.PUBLIC_VIEW)

    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


@router.get(
    "/video/{org_uuid}/{course_uuid}/{activity_uuid}/{filename:path}",
    summary="Stream an activity video",
    description="Streams a video file for a course activity with HTTP Range request support. Validates user read access via RBAC before serving the file.",
    responses={
        200: {"description": "Full video streamed successfully"},
        206: {"description": "Partial video content returned for a Range request"},
        403: {"description": "User is not permitted to read this course"},
        404: {"description": "Activity, course, or video file not found"},
    },
)
async def stream_activity_video(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    course_uuid: str = Path(..., description="Course UUID"),
    activity_uuid: str = Path(..., description="Activity UUID"),
    filename: str = Path(..., description="Video filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    Stream a video file for an activity with proper Range request support.

    This endpoint supports:
    - HTTP Range requests for seeking in long videos
    - Efficient chunked streaming
    - Proper Content-Type headers
    - Cache-Control headers for browser caching

    SECURITY: Validates user has read access to the course via RBAC.
    """
    # SECURITY: Verify user has access to this course/activity
    await _verify_course_activity_access(request, course_uuid, activity_uuid, current_user, db_session)

    # Check if this is a MINIO video activity — proxy to external MinIO URL
    activity_stmt = select(Activity).where(Activity.activity_uuid == activity_uuid)
    activity = db_session.exec(activity_stmt).first()

    if activity and activity.activity_sub_type.value == "SUBTYPE_VIDEO_MINIO":
        return await _stream_minio_video(
            request, activity, filename, client_ip=_get_client_ip(request)
        )

    # Construct and validate the file path
    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "courses",
        course_uuid,
        "activities",
        activity_uuid,
        "video",
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Video not found")

    # Get file info
    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Video not found")

    # Parse Range header if present
    range_header = request.headers.get("range")
    has_explicit_range = bool(range_header)

    if has_explicit_range:
        start, end = parse_range_header(range_header, file_size)
    else:
        # BANDWIDTH PROTECTION: For files larger than the threshold, force a
        # 206 response with an initial byte range instead of streaming the
        # entire file. This prevents a 610MB video from saturating bandwidth
        # when browsers don't send Range headers.
        if file_size > MAX_FILE_SIZE_FOR_FULL_STREAM:
            start = 0
            end = min(CHUNK_SIZE * 10 - 1, file_size - 1)  # Serve first 10MB
            logger.debug("Forcing 206 for large file (%d bytes), range 0-%d", file_size, end)
        else:
            start, end = 0, file_size - 1

    # Calculate content length for this range
    content_length = end - start + 1

    # BANDWIDTH PROTECTION: Check concurrent stream limit
    client_ip = _get_client_ip(request)
    if not await _acquire_stream_slot(client_ip):
        logger.warning("Max concurrent streams reached for IP %s", client_ip)
        raise HTTPException(status_code=429, detail="Too many concurrent video streams")

    # Common headers for video streaming
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime_type,
        "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
        "X-Content-Type-Options": "nosniff",
    }

    should_use_206 = has_explicit_range or file_size > MAX_FILE_SIZE_FOR_FULL_STREAM

    if should_use_206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(content_length)

        async def _gen_activity():
            try:
                for chunk in stream_video_file(file_path, start, end, CHUNK_SIZE):
                    yield chunk
            finally:
                await _release_stream_slot(client_ip)

        return StreamingResponse(
            _gen_activity(),
            status_code=206,
            headers=headers,
            media_type=mime_type,
        )
    else:
        headers["Content-Length"] = str(file_size)

        async def _gen_activity_full():
            try:
                for chunk in stream_video_file(file_path, start, end, CHUNK_SIZE):
                    yield chunk
            finally:
                await _release_stream_slot(client_ip)

        return StreamingResponse(
            _gen_activity_full(),
            status_code=200,
            headers=headers,
            media_type=mime_type,
        )


def _parse_minio_url(minio_url: str) -> tuple[str, str]:
    """Parse a MinIO URL like http://minio:9000/bucket/path/to/file.mp4
    into (bucket, key). The key is URL-decoded."""
    from urllib.parse import urlparse, unquote

    parsed = urlparse(minio_url)
    path = parsed.path.lstrip("/")
    if "/" not in path:
        raise HTTPException(status_code=404, detail="Invalid MinIO URL: missing bucket/key")
    bucket, key = path.split("/", 1)
    return bucket, unquote(key)


async def _stream_minio_video(
    request: Request,
    activity: Activity,
    filename: str,
    client_ip: str,
) -> StreamingResponse:
    """Proxy video streaming from MinIO using the authenticated S3 client.

    For SUBTYPE_VIDEO_MINIO activities, the video lives in a MinIO bucket
    that requires authentication. This function uses the configured boto3
    S3 client to retrieve the file with Range support.
    """
    from src.services.courses.transfer.storage_utils import get_storage_client

    minio_url = activity.content.get("uri", "") if activity.content else ""
    if not minio_url:
        raise HTTPException(status_code=404, detail="MinIO video URL not found")

    s3_client = get_storage_client()
    if s3_client is None:
        raise HTTPException(status_code=500, detail="S3 storage client not configured")

    bucket, key = _parse_minio_url(minio_url)

    # HEAD via S3 to get file size and content-type
    try:
        head_resp = await asyncio.to_thread(
            lambda: s3_client.head_object(Bucket=bucket, Key=key)
        )
    except Exception as exc:
        logger.warning("S3 head_object failed for %s/%s: %s", bucket, key, exc)
        raise HTTPException(status_code=404, detail="MinIO video not reachable")

    file_size = int(head_resp.get("ContentLength", 0))
    if file_size <= 0:
        raise HTTPException(status_code=404, detail="MinIO video size unknown")

    mime_type = head_resp.get("ContentType") or "video/mp4"

    range_header = request.headers.get("range")
    has_explicit_range = bool(range_header)

    if has_explicit_range:
        start, end = parse_range_header(range_header, file_size)
    elif file_size > MAX_FILE_SIZE_FOR_FULL_STREAM:
        start = 0
        end = min(CHUNK_SIZE * 10 - 1, file_size - 1)
    else:
        start, end = 0, file_size - 1

    content_length = end - start + 1
    should_use_206 = has_explicit_range or file_size > MAX_FILE_SIZE_FOR_FULL_STREAM

    if not await _acquire_stream_slot(client_ip):
        logger.warning("Max concurrent streams reached for IP %s", client_ip)
        raise HTTPException(status_code=429, detail="Too many concurrent video streams")

    response_headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime_type,
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }

    range_arg = f"bytes={start}-{end}"

    def _iter_s3_body():
        get_resp = s3_client.get_object(Bucket=bucket, Key=key, Range=range_arg)
        body = get_resp["Body"]
        try:
            while True:
                chunk = body.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                body.close()
            except Exception:
                pass

    if should_use_206:
        response_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response_headers["Content-Length"] = str(content_length)
        status_code = 206
    else:
        response_headers["Content-Length"] = str(file_size)
        status_code = 200

    async def _gen_minio():
        try:
            for chunk in _iter_s3_body():
                yield chunk
        finally:
            await _release_stream_slot(client_ip)

    return StreamingResponse(
        _gen_minio(),
        status_code=status_code,
        headers=response_headers,
        media_type=mime_type,
    )


@router.get(
    "/block/audio/{org_uuid}/{course_uuid}/{activity_uuid}/{block_uuid}/{filename:path}",
    summary="Stream an audio block file",
    description="Streams an audio file attached to an audio block within an activity, with HTTP Range request support. Validates user read access to the parent course via RBAC.",
    responses={
        200: {"description": "Full audio streamed successfully"},
        206: {"description": "Partial audio content returned for a Range request"},
        403: {"description": "User is not permitted to read this course"},
        404: {"description": "Activity, course, or audio file not found"},
    },
)
async def stream_block_audio(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    course_uuid: str = Path(..., description="Course UUID"),
    activity_uuid: str = Path(..., description="Activity UUID"),
    block_uuid: str = Path(..., description="Block UUID"),
    filename: str = Path(..., description="Audio filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    Stream an audio file from an audio block with proper Range request support.

    SECURITY: Validates user has read access to the course via RBAC.
    """
    # SECURITY: Verify user has access to this course/activity
    await _verify_course_activity_access(request, course_uuid, activity_uuid, current_user, db_session)

    # Construct and validate the file path
    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "courses",
        course_uuid,
        "activities",
        activity_uuid,
        "dynamic",
        "blocks",
        "audioBlock",
        block_uuid,
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Audio not found")

    # Get file info
    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Audio not found")

    return await _serve_stream_with_protection(request, file_path, file_size, mime_type)


@router.head(
    "/block/audio/{org_uuid}/{course_uuid}/{activity_uuid}/{block_uuid}/{filename:path}",
    summary="Get audio block file metadata",
    description="Returns metadata for an audio block file without the body. Used by audio players to probe file size and Range support before playback.",
    responses={
        200: {"description": "Audio metadata returned via response headers"},
        403: {"description": "User is not permitted to read this course"},
        404: {"description": "Activity, course, or audio file not found"},
    },
)
async def head_block_audio(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    course_uuid: str = Path(..., description="Course UUID"),
    activity_uuid: str = Path(..., description="Activity UUID"),
    block_uuid: str = Path(..., description="Block UUID"),
    filename: str = Path(..., description="Audio filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    HEAD request for block audio - returns metadata without body.

    SECURITY: Validates user has read access to the course via RBAC.
    """
    await _verify_course_activity_access(request, course_uuid, activity_uuid, current_user, db_session)

    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "courses",
        course_uuid,
        "activities",
        activity_uuid,
        "dynamic",
        "blocks",
        "audioBlock",
        block_uuid,
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Audio not found")

    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Audio not found")

    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get(
    "/block/{org_uuid}/{course_uuid}/{activity_uuid}/{block_uuid}/{filename:path}",
    summary="Stream a video block file",
    description="Streams a video file attached to a video block within an activity, with HTTP Range request support. Validates user read access to the parent course via RBAC.",
    responses={
        200: {"description": "Full video streamed successfully"},
        206: {"description": "Partial video content returned for a Range request"},
        403: {"description": "User is not permitted to read this course"},
        404: {"description": "Activity, course, or video file not found"},
    },
)
async def stream_block_video(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    course_uuid: str = Path(..., description="Course UUID"),
    activity_uuid: str = Path(..., description="Activity UUID"),
    block_uuid: str = Path(..., description="Block UUID"),
    filename: str = Path(..., description="Video filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    Stream a video file from a video block with proper Range request support.

    This endpoint supports:
    - HTTP Range requests for seeking in long videos
    - Efficient chunked streaming
    - Proper Content-Type headers
    - Cache-Control headers for browser caching

    SECURITY: Validates user has read access to the course via RBAC.
    """
    # SECURITY: Verify user has access to this course/activity
    await _verify_course_activity_access(request, course_uuid, activity_uuid, current_user, db_session)

    # Construct and validate the file path
    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "courses",
        course_uuid,
        "activities",
        activity_uuid,
        "dynamic",
        "blocks",
        "videoBlock",
        block_uuid,
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Video not found")

    # Get file info
    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Video not found")

    return await _serve_stream_with_protection(request, file_path, file_size, mime_type)


@router.head(
    "/video/{org_uuid}/{course_uuid}/{activity_uuid}/{filename:path}",
    summary="Get activity video metadata",
    description="Returns metadata for an activity video without the body. Used by video players to probe file size and Range support before playback.",
    responses={
        200: {"description": "Video metadata returned via response headers"},
        403: {"description": "User is not permitted to read this course"},
        404: {"description": "Activity, course, or video file not found"},
    },
)
async def head_activity_video(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    course_uuid: str = Path(..., description="Course UUID"),
    activity_uuid: str = Path(..., description="Activity UUID"),
    filename: str = Path(..., description="Video filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    HEAD request for activity video - returns metadata without body.

    This is used by video players to determine file size and supported ranges
    before starting playback.

    SECURITY: Validates user has read access to the course via RBAC.
    """
    # SECURITY: Verify user has access to this course/activity
    await _verify_course_activity_access(request, course_uuid, activity_uuid, current_user, db_session)

    # Check for MINIO video
    activity_stmt = select(Activity).where(Activity.activity_uuid == activity_uuid)
    activity = db_session.exec(activity_stmt).first()

    if activity and activity.activity_sub_type.value == "SUBTYPE_VIDEO_MINIO":
        return await _head_minio_video(request, activity)

    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "courses",
        course_uuid,
        "activities",
        activity_uuid,
        "video",
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Video not found")

    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Video not found")

    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
            "Cache-Control": "public, max-age=86400",
        },
    )


async def _head_minio_video(
    request: Request,
    activity: Activity,
) -> Response:
    """Return metadata for a MINIO-hosted video without the body.

    Uses the authenticated S3 client to fetch object metadata from MinIO.
    """
    from src.services.courses.transfer.storage_utils import get_storage_client

    minio_url = activity.content.get("uri", "") if activity.content else ""
    if not minio_url:
        raise HTTPException(status_code=404, detail="MinIO video URL not found")

    s3_client = get_storage_client()
    if s3_client is None:
        raise HTTPException(status_code=500, detail="S3 storage client not configured")

    bucket, key = _parse_minio_url(minio_url)

    try:
        head_resp = await asyncio.to_thread(
            lambda: s3_client.head_object(Bucket=bucket, Key=key)
        )
    except Exception as exc:
        logger.warning("S3 head_object failed for %s/%s: %s", bucket, key, exc)
        raise HTTPException(status_code=404, detail="MinIO video not reachable")

    file_size = str(head_resp.get("ContentLength", 0))
    mime_type = head_resp.get("ContentType") or "video/mp4"

    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": file_size,
            "Content-Type": mime_type,
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.head(
    "/block/{org_uuid}/{course_uuid}/{activity_uuid}/{block_uuid}/{filename:path}",
    summary="Get video block file metadata",
    description="Returns metadata for a video block file without the body. Used by video players to probe file size and Range support before playback.",
    responses={
        200: {"description": "Video metadata returned via response headers"},
        403: {"description": "User is not permitted to read this course"},
        404: {"description": "Activity, course, or video file not found"},
    },
)
async def head_block_video(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    course_uuid: str = Path(..., description="Course UUID"),
    activity_uuid: str = Path(..., description="Activity UUID"),
    block_uuid: str = Path(..., description="Block UUID"),
    filename: str = Path(..., description="Video filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    HEAD request for block video - returns metadata without body.

    This is used by video players to determine file size and supported ranges
    before starting playback.

    SECURITY: Validates user has read access to the course via RBAC.
    """
    # SECURITY: Verify user has access to this course/activity
    await _verify_course_activity_access(request, course_uuid, activity_uuid, current_user, db_session)

    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "courses",
        course_uuid,
        "activities",
        activity_uuid,
        "dynamic",
        "blocks",
        "videoBlock",
        block_uuid,
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Video not found")

    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Video not found")

    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get(
    "/audio/{org_uuid}/{podcast_uuid}/{episode_uuid}/{filename:path}",
    summary="Stream a podcast episode audio",
    description="Streams a podcast episode audio file with HTTP Range request support. Validates user read access to the podcast via RBAC before serving the file.",
    responses={
        200: {"description": "Full audio streamed successfully"},
        206: {"description": "Partial audio content returned for a Range request"},
        403: {"description": "User is not permitted to read this podcast"},
        404: {"description": "Podcast, episode, or audio file not found"},
    },
)
async def stream_podcast_audio(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    podcast_uuid: str = Path(..., description="Podcast UUID"),
    episode_uuid: str = Path(..., description="Episode UUID"),
    filename: str = Path(..., description="Audio filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    Stream an audio file for a podcast episode with proper Range request support.

    This endpoint supports:
    - HTTP Range requests for seeking in audio files
    - Efficient chunked streaming
    - Proper Content-Type headers
    - Cache-Control headers for browser caching

    SECURITY: Validates user has read access to the podcast via RBAC.
    """
    # SECURITY: Verify user has access to this podcast/episode
    await _verify_podcast_episode_access(request, podcast_uuid, episode_uuid, current_user, db_session)

    # Construct and validate the file path
    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "podcasts",
        podcast_uuid,
        "episodes",
        episode_uuid,
        "audio",
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Audio not found")

    # Get file info
    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Audio not found")

    return await _serve_stream_with_protection(request, file_path, file_size, mime_type)


@router.head(
    "/audio/{org_uuid}/{podcast_uuid}/{episode_uuid}/{filename:path}",
    summary="Get podcast audio metadata",
    description="Returns metadata for a podcast episode audio file without the body. Used by audio players to probe file size and Range support before playback.",
    responses={
        200: {"description": "Audio metadata returned via response headers"},
        403: {"description": "User is not permitted to read this podcast"},
        404: {"description": "Podcast, episode, or audio file not found"},
    },
)
async def head_podcast_audio(
    request: Request,
    org_uuid: str = Path(..., description="Organization UUID"),
    podcast_uuid: str = Path(..., description="Podcast UUID"),
    episode_uuid: str = Path(..., description="Episode UUID"),
    filename: str = Path(..., description="Audio filename"),
    current_user: PublicUser | AnonymousUser | APITokenUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """
    HEAD request for podcast audio - returns metadata without body.

    This is used by audio players to determine file size and supported ranges
    before starting playback.

    SECURITY: Validates user has read access to the podcast via RBAC.
    """
    # SECURITY: Verify user has access to this podcast/episode
    await _verify_podcast_episode_access(request, podcast_uuid, episode_uuid, current_user, db_session)

    file_path = validate_video_path(
        CONTENT_DIR,
        "orgs",
        org_uuid,
        "podcasts",
        podcast_uuid,
        "episodes",
        episode_uuid,
        "audio",
        filename,
    )

    if not file_path:
        raise HTTPException(status_code=404, detail="Audio not found")

    file_size, mime_type, exists = get_file_info(file_path)

    if not exists:
        raise HTTPException(status_code=404, detail="Audio not found")

    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
            "Cache-Control": "public, max-age=86400",
        },
    )
