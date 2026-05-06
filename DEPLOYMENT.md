# LearnHouse 部署文档

**修复**: 视频播放带宽饱和问题
**Commit**: `5597d53`
**日期**: 2026-05-06
**Docker 镜像**: `learnhouse:latest` (1.1GB) → `learnhouse-fixed.tar`

---

## 1. 问题描述

610MB 视频播放时打满服务器带宽但无法正常播放。根因：
- `GZipMiddleware` 对所有响应（包括视频流）进行 gzip 压缩
- 压缩后视频响应丢失 `Content-Length`，改用 `chunked` 传输
- `<video>` 元素无法 seek，持续拉取完整 610MB

## 2. 修复内容（三层防护）

| 层级 | 文件 | 修复 |
|---|---|---|
| 中间件 | `app.py` | `SafeGZipMiddleware` 跳过 `/stream/` 和 `/content/` 路径 |
| 带宽保护 | `stream.py` + `video_streaming.py` | >50MB 强制 206 + 10MB 切片 + 每 IP 最多 5 并发流 |
| 前端 | 5 个组件 | `<video>/<audio>` 添加 `crossOrigin="use-credentials"` |
| 认证 | `auth.py` | 新增 `?token=` 查询参数 JWT 回退 |

详细变更见 `GIT_DIFF_REPORT.md`。

## 3. 构建与部署

### 3.1 构建镜像
```bash
cd /data/service/learnhouse
docker build -t learnhouse:latest .
docker save learnhouse:latest -o learnhouse-fixed.tar
```

### 3.2 启动服务
```bash
docker compose up -d
```

### 3.3 健康检查
```bash
curl http://localhost:9001/api/v1/health   # 返回 true
```

## 4. 回归测试

```bash
bash test-video-playback.sh
```

结果：**22/22 PASS, 0 FAIL**

| 测试项 | 结果 |
|---|---|
| 登录认证 | PASS |
| 后端 Range 请求 (0-1023) | 206, 精确 1024 bytes |
| 后端 Content-Range / Accept-Ranges | PASS |
| MinIO 文件存在性 | PASS |
| 后端中间 Range (2048-4095) | 206, 精确 2048 bytes |
| 前端代理 Range 请求 (8088) | 206, 正确转发 |
| ?token= 查询参数认证 | PASS |
| 后端无 Range 带宽保护 | 强制 206, Content-Length = 10MB |
| 前端代理无 Range 带宽保护 | 强制 206, Content-Length = 10MB |
| 前端显式 1MB Range | 206 |

## 5. 端口参考

| 组件 | 端口 | 说明 |
|---|---|---|
| Backend API | 9001 | 直接访问 |
| Frontend (nginx) | 8088 | 前端入口 |
| MinIO | 9000 / 9091 | API / 控制台 |
| PostgreSQL | 15432 | 数据库 |
| Redis | 16379 | 缓存 |

## 6. 回滚方案

### 方案 A: 恢复旧镜像
```bash
docker load -i learnhouse-latest.tar   # 旧镜像 (无修复)
docker compose up -d
```

### 方案 B: 恢复旧代码 + 重启
```bash
cd /data/service/learnhouse
git checkout <pre-fix-commit>   # 如果已有 git 历史
docker compose restart app
```

## 7. 附件

| 文件 | 大小 | 说明 |
|---|---|---|
| `learnhouse-fixed.tar` | 1.1GB | 含修复的新镜像 |
| `learnhouse-latest.tar` | 1.1GB | 修复前的旧镜像 |
| `GIT_DIFF_REPORT.md` | - | 逐文件变更对比 |
| `CHANGES.md` | - | 变更摘要 |
| `test-video-playback.sh` | - | 回归测试脚本 |
