# MinIO 视频适配改动文档

## 背景

项目部署在 S3 (MinIO) 模式下时，视频文件不落地到本地文件系统，而是存储在 MinIO 桶中。浏览器无法直接访问内网 MinIO 地址（CORS / 网络不通）。本次改动实现了从"MinIO URL 创建课程"到"后端代理流式播放"的完整链路。

---

## 核心改动

### 1. 新增 Activity 子类型 `SUBTYPE_VIDEO_MINIO`

**文件:** `apps/api/src/db/courses/activities.py`

新增 `ActivitySubTypeEnum.SUBTYPE_VIDEO_MINIO = "SUBTYPE_VIDEO_MINIO"`，用于区分：
- `SUBTYPE_VIDEO_HOSTED` — 视频文件上传到本地/S3 文件系统
- `SUBTYPE_VIDEO_YOUTUBE` — YouTube 外链
- `SUBTYPE_VIDEO_MINIO` — MinIO URL 引用，视频不落地，由后端代理流式播放

Activity `content` 字段结构：
```json
{
  "uri": "http://minio:9000/bucket/path/to/video.mp4",
  "type": "minio",
  "activity_uuid": "activity_xxx",
  "filename": "video.mp4"
}
```

### 2. 后端流式端点扩展 — MinIO 视频代理

**文件:** `apps/api/src/routers/stream.py`

`stream_activity_video` 端点增加了 MinIO 分支：
- 检查 activity 的 `activity_sub_type`，如果是 `SUBTYPE_VIDEO_MINIO`，走 `_stream_minio_video()`
- 使用 `storage_utils.get_storage_client()` 获取已配置的 S3/boto3 客户端
- 通过 `head_object` 获取文件大小和 Content-Type
- 支持 HTTP Range 请求（206 Partial Content），与本地视频流一致
- 同样受并发流限制（每 IP 最多 5 个并发）和大文件带宽保护

对应新增 `head_activity_video` 的 MinIO 分支 (`_head_minio_video`)，用于视频播放器预取元数据。

### 3. MinIO URL 批量创建课程

**文件:** `apps/api/src/routers/courses/migration.py`

新增端点 `POST /courses/migrate/create_from_urls`，接收 `MigrationUrlStructure`：
```json
{
  "structure": {
    "course_name": "...",
    "course_description": "...",
    "chapters": [
      {
        "name": "第一章",
        "videos": [
          { "name": "视频1", "uri": "http://minio:9000/bucket/vid1.mp4", "details": "{}" }
        ]
      }
    ]
  }
}
```

每个 URL 创建一个 `SUBTYPE_VIDEO_MINIO` 活动，不上传任何文件。

**文件:** `apps/api/src/services/courses/migration/models.py`

新增 Pydantic 模型：
- `MinIOVideoNode` — 单个 MinIO 视频节点 (name + uri + details)
- `MigrationUrlChapter` — 章节含多个 MinIO 视频
- `MigrationUrlStructure` — 完整 URL 课程结构
- `CreateFromURLsRequest` — 创建请求体

**文件:** `apps/api/src/services/courses/migration/migration_service.py`

新增 `create_course_from_urls()` 函数：
- 校验用户权限（非匿名、有创建课程权限）
- 遍历结构创建 course → chapter → activity
- activity 类型为 `TYPE_VIDEO`，子类型为 `SUBTYPE_VIDEO_MINIO`
- `content.uri` 存储完整 MinIO URL
- `details` 中存储从 URL 提取的 filename

### 4. 前端 URL 迁移向导

**文件:** `apps/web/app/orgs/[orgslug]/dash/courses/migrate/client.tsx`

- 新增 Upload Mode 切换：`files`（本地上传）/ `urls`（MinIO 路径）
- `urls` 模式下显示 `MigrationUrlInput` 组件
- 调用 `createCourseFromUrls` 服务创建课程

**文件:** `apps/web/components/Objects/Modals/Course/Create/MigrationWizard/MigrationUrlInput.tsx` (新增)

MinIO URL 输入组件，支持逐条添加/删除 URL，自动从 URL 提取视频名称。

### 5. 前端单个活动 — MinIO 视频创建

**文件:** `apps/web/components/Objects/Modals/Activities/Create/NewActivityModal/VideoActivityModal.tsx`

视频创建弹窗增加 "MinIO" 标签页，输入 MinIO URL 后调用 `submitMinIOVideo` 创建 `SUBTYPE_VIDEO_MINIO` 活动。

**文件:** `apps/web/components/Objects/Modals/Activities/Create/NewActivity.tsx`

将 `submitMinIOVideo` 回调传递到 `VideoModal`。

**文件:** `apps/web/components/Dashboard/Pages/Course/EditCourseStructure/Buttons/NewActivityButton.tsx`

新增 `submitMinIOVideo` 处理函数，向 API 提交 MinIO 视频活动。

### 6. 前端播放适配

**文件:** `apps/web/components/Objects/Activities/Video/Video.tsx`

`VideoActivity` 组件增加 `SUBTYPE_VIDEO_MINIO` 分支：
- 使用后端 stream 端点 (`/stream/video/...`) 作为视频源
- 浏览器不直接连接 MinIO，避免 CORS 和内网不可达问题
- 与 `SUBTYPE_VIDEO_HOSTED` 共用 `LearnHousePlayer`

**文件:** `apps/web/services/courses/activities.ts`

新增 MinIO 视频活动提交逻辑。

### 7. 国际化

**文件:** `apps/web/locales/en.json` / `apps/web/locales/zh.json`

新增迁移页面文案：`migration.minio_urls`、`migration.create_course` 等。

---

## 架构总结

```
用户粘贴 MinIO URL → 后端创建 SUBTYPE_VIDEO_MINIO activity（content.uri = MinIO URL）
                                              ↓
用户观看视频 → 前端请求 /stream/video/{org}/{course}/{activity}/{filename}
                                              ↓
                                    stream.py 识别 SUBTYPE_VIDEO_MINIO
                                              ↓
                                    用 boto3 S3 客户端 get_object(Range=...) 代理流
                                              ↓
                                    返回 200/206 StreamingResponse 给浏览器
```

关键设计决策：
1. **不直连 MinIO** — 浏览器通过后端代理访问视频，解决内网 MinIO 不可达
2. **复用已有 stream 端点** — Range 支持、并发限制、带宽保护全部自动生效
3. **新 activity_sub_type 而非新端点** — 最小侵入，stream 路由内部分支处理
