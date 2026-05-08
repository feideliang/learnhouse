# ClickHouse 整改报告

## 背景

ClickHouse 容器运行期间出现资源占用过高问题：
- 磁盘占用 893MB+（系统日志无限增长）
- 无内存/CPU 限制
- 应用表 `events` 不存在（建表 DDL 文件是空目录）
- 空密码

## 整改内容

### 1. 新建 `docker/init-clickhouse.sql`

**之前**：`init-clickhouse.sql` 是空目录，导致容器启动时未执行任何初始化
**现在**：建表 SQL，创建 `learnhouse.events` 表

```sql
CREATE TABLE IF NOT EXISTS learnhouse.events (
    timestamp DateTime,
    event_name LowCardinality(String),
    org_id UInt64,
    user_id UInt64,
    session_id String,
    properties String,
    source LowCardinality(String),
    ip IPv4
) ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (event_name, org_id, timestamp)
TTL timestamp + INTERVAL 90 DAY;
```

### 2. 新建 `docker/clickhouse-config.xml`

**之前**：11 张系统日志表全部开启，无限增长
**现在**：禁用 4 张重型日志表，日志级别降为 warning

- 移除 `trace_log`（最大单表，曾占 399MB）
- 移除 `query_log`
- 移除 `asynchronous_metric_log`（6700万行）
- 移除 `background_schedule_pool_log`
- 保留 `metric_log`、`part_log`、`text_log`

### 3. 修改 `docker-compose.yml`

| 配置项 | 修改前 | 修改后 |
|--------|--------|--------|
| ClickHouse 密码 | 空 | `learnhouse-ch` |
| 内存上限 | 无 | 4GB |
| 内存保留 | 无 | 1GB |
| CPU 上限 | 无 | 1.5 核 |
| 配置文件挂载 | 无 | 挂载 clickhouse-config.xml |

## 整改效果

| 指标 | 整改前 | 整改后 |
|------|--------|--------|
| 磁盘占用 | ~1.6GB | 286MB (-82%) |
| 内存限制 | 无上限 | 4GB (实际 550MB) |
| CPU 限制 | 无上限 | 1.5 核 |
| events 表 | 不存在 | 已创建，TTL 90天 |
| 密码 | 空 | 已设置 |
| 容器状态 | unstable | healthy |

## 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `docker-compose.yml` | 修改 |
| `docker/init-clickhouse.sql` | 新增 |
| `docker/clickhouse-config.xml` | 新增 |

**注意**：本次整改仅涉及后端基础设施配置，不涉及任何前端代码修改。
