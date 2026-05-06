# Changes Summary

## Problem
610MB video files caused bandwidth saturation and playback failure.
GZipMiddleware compressed ALL responses including video streams, breaking
HTTP Range requests and causing browsers to continuously fetch the full file.

## Fix (3 layers)

### 1. SafeGZipMiddleware (app.py)
- Created SafeGZipMiddleware subclass that skips /stream/, /api/v1/stream/, /content/ paths
- Prevents GZip from compressing video/audio streaming responses

### 2. Bandwidth Protection (stream.py, video_streaming.py)
- Files >50MB force 206 Partial Content with 10MB initial slice
- Prevents full-file streaming when no Range header is sent
- Per-IP concurrent stream limit (max 5 sessions)
- Stream timeout (120s idle) to prevent zombie connections

### 3. Frontend crossOrigin (5 components)
- Added crossOrigin="use-credentials" to all <video>/<audio> elements
- Enables browser to send cookies with Range requests

### 4. Auth Fallback (auth.py)
- Added ?token= query parameter support for JWT
- Priority: Authorization header > cookie > query param

## Files Changed
- learnhouse/apps/api/app.py
- learnhouse/apps/api/src/routers/stream.py
- learnhouse/apps/api/src/services/utils/video_streaming.py
- learnhouse/apps/api/src/security/auth.py
- learnhouse/apps/web/components/Objects/Activities/Video/LearnHousePlayer.tsx
- learnhouse/apps/web/components/Objects/Editor/Blocks/VideoBlock/VideoBlockComponent.tsx
- learnhouse/apps/web/components/Objects/Editor/Blocks/PodcastBlock/PodcastBlockComponent.tsx
- learnhouse/apps/web/components/Objects/Player/PodcastPlayer.tsx
- learnhouse/apps/web/components/Objects/Editor/Blocks/AudioBlock/AudioBlockComponent.tsx
- test-video-playback.sh (new)

## Verification
- 22/22 regression tests passing
- Range requests return 206 with correct Content-Range
- No-Range requests on large files return 206 with 10MB slice (not 200 with full file)
- Frontend proxy correctly forwards Range headers
- ?token= authentication works
