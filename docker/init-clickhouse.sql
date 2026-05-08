-- Learnhouse ClickHouse initialization script
-- Creates the events table for analytics

-- Ensure the application database exists
CREATE DATABASE IF NOT EXISTS learnhouse;

-- Main analytics events table
-- TTL: auto-delete events older than 90 days
CREATE TABLE IF NOT EXISTS learnhouse.events
(
    `timestamp` DateTime,
    `event_name` LowCardinality(String),
    `org_id` UInt64,
    `user_id` UInt64,
    `session_id` String,
    `properties` String,
    `source` LowCardinality(String),
    `ip` IPv4
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (event_name, org_id, timestamp)
TTL timestamp + INTERVAL 90 DAY;
