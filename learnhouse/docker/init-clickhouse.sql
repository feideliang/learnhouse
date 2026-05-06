CREATE TABLE IF NOT EXISTS events
(
    `event_name` String,
    `timestamp` DateTime,
    `org_id` UInt32,
    `user_id` UInt32,
    `session_id` String,
    `properties` String,
    `source` String,
    `ip` String
)
ENGINE = MergeTree()
ORDER BY (org_id, event_name, timestamp);
