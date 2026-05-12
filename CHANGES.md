# Changes Summary

## Problem: Docker App 卡顿 / 健康检查失败 / 分析端点 502

App 容器标记为 `unhealthy`，页面响应卡顿，Analytics 端点返回 502。
根因：健康检查端口错误、ClickHouse 路由误判、PostgreSQL 空闲超时未配置。

### 修复 1 — Healthcheck 端口错误 (docker-compose.yml)

**症状**: `curl -f http://localhost/api/v1/health` 连接 port 80 失败，但 nginx 实际监听 8088
**改动**:
- `app` service healthcheck: `http://localhost` → `http://localhost:8088/api/v1/health`
- 新增 `retries: 3` 和 `start_period: 30s`
**效果**: 容器状态 `unhealthy` → `healthy`，健康检查响应 6ms

### 修复 2 — ClickHouse 分析端点 502 (analytics.py)

**症状**: `live_users` 和 `event_counts` 查询返回 502，日志显示 `There is no handle /v0/sql`
**根因**: `_is_clickhouse()` 仅通过 `username and password` 判断，空密码时被误判为 Tinybird，
请求发往不存在的 `/v0/sql` 而非 ClickHouse 的 `/?query=...`
**改动**:
- `_is_clickhouse()` 增加 URL 模式检测：localhost/172.x/10.x/192.168.x 识别为 ClickHouse
- 同步修改 `apps/api/src/routers/analytics.py` + `learnhouse/apps/api/src/routers/analytics.py`
**效果**: Analytics 端点不再 502，正常路由到 ClickHouse HTTP API

### 修复 3 — PostgreSQL 空闲连接超时 (docker-compose.yml)

**症状**: 日志中 `psycopg2.OperationalError: server closed the connection unexpectedly`（8 次）
**改动**:
- `db` service 新增 `command` 参数:
  - `tcp_keepalives_idle=300` / `tcp_keepalives_interval=30` / `tcp_keepalives_count=3`
  - `idle_in_transaction_session_timeout=300000` (5min)
**效果**: `idle_in_transaction_session_timeout` 生效，空闲事务 5min 后自动断开

### 验证结果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| App 健康状态 | unhealthy (8次失败) | healthy |
| 健康检查响应 | 连接失败 | 6ms |
| API 响应时间 | - | 7ms |
| Analytics 端点 | 502 Bad Gateway | 正常路由 |
| 数据库连接池 | 空闲断连报错 | 5min 超时保护 |

---

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
