# Git Diff Report

**对比基准**: Docker 镜像 learnhouse:latest (2026-04-30) 中的代码
**对比对象**: 本地修改后的代码 (learnhouse/)

---

## 变更文件清单

### 1. apps/api/app.py — SafeGZipMiddleware
- **新增** SafeGZipMiddleware 类 (~25 行) — 跳过 /stream/, /api/v1/stream/, /content/ 路径的 GZip
- **修改** 注册中间件 GZipMiddleware → SafeGZipMiddleware
- **新增** S3 content_files_router 的 /api/v1 前缀注册

### 2. apps/api/src/routers/stream.py — 带宽保护
- **新增** 每 IP 并发流限制器 (max 5) + IP 提取函数
- **新增** _serve_stream_with_protection() 统一流处理
- **新增** 无 Range 时 >50MB 强制 206 + 10MB 切片
- **修改** stream_activity_video 端点统一使用保护逻辑

### 3. apps/api/src/services/utils/video_streaming.py — 常量
- **新增** MAX_FILE_SIZE_FOR_FULL_STREAM (50MB), STREAM_TIMEOUT_SECONDS (120s)
- **修改** S3 validate_video_path 路径前缀修复

### 4. apps/api/src/security/auth.py — 查询参数认证
- **新增** ?token= 查询参数 JWT 回退 (优先级: Header > Cookie > Query)
- **新增** API token 也支持 ?token=lh_... 查询

### 5. 前端组件 (5 个文件)
- LearnHousePlayer.tsx — video crossOrigin="use-credentials"
- VideoBlockComponent.tsx — video crossOrigin + TS 类型修复
- PodcastBlockComponent.tsx — audio crossOrigin
- PodcastPlayer.tsx — audio crossOrigin
- AudioBlockComponent.tsx — audio crossOrigin

### 6. test-video-playback.sh — 回归测试 (新增)
- 22 项测试覆盖: Range 请求、带宽保护、前端代理、?token= 认证
