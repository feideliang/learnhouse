import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

import httpx

from config.config import get_learnhouse_config

logger = logging.getLogger(__name__)

# Lazy singleton httpx client for analytics ingestion
_ingest_client: httpx.AsyncClient | None = None

# Strong references so the GC does not collect tasks before they complete
_background_tasks: set = set()


def _get_ingest_client() -> httpx.AsyncClient | None:
    global _ingest_client
    if _ingest_client is not None:
        return _ingest_client

    config = get_learnhouse_config()
    tb = config.tinybird_config
    if tb is None:
        return None

    # ClickHouse: use Basic auth with username and password (may be empty)
    headers = {}
    if tb.username:
        auth = httpx.BasicAuth(tb.username, tb.password or "")
        headers["Content-Type"] = "application/json"
    elif tb.ingest_token:
        # Tinybird fallback: Bearer token
        headers["Authorization"] = f"Bearer {tb.ingest_token}"

    _ingest_client = httpx.AsyncClient(
        base_url=tb.api_url,
        auth=auth,
        headers=headers,
        timeout=10.0,
    )
    return _ingest_client


def _is_clickhouse() -> bool:
    """Detect if we're talking to ClickHouse (has username/password or API URL points to ClickHouse) vs Tinybird."""
    config = get_learnhouse_config()
    tb = config.tinybird_config
    if tb is None:
        return False
    if tb.username and tb.password:
        return True
    # Also detect ClickHouse by URL pattern (port 8123 or clickhouse hostname)
    api_url = (tb.api_url or "").lower()
    if ":8123" in api_url or "clickhouse" in api_url:
        return True
    return False


async def track(
    event_name: str,
    org_id: int,
    user_id: int = 0,
    session_id: str = "",
    properties: dict | None = None,
    source: str = "api",
    ip: str = "",
) -> None:
    """
    Fire-and-forget analytics event to ClickHouse/Tinybird.
    All errors are swallowed and logged — analytics never breaks the app.
    """
    config = get_learnhouse_config()
    if config.tinybird_config is None:
        return

    task = asyncio.create_task(
        _send_event(
            event_name=event_name,
            org_id=org_id,
            user_id=user_id,
            session_id=session_id,
            properties=properties or {},
            source=source,
            ip=ip,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _send_event(
    event_name: str,
    org_id: int,
    user_id: int,
    session_id: str,
    properties: dict,
    source: str,
    ip: str,
) -> None:
    try:
        client = _get_ingest_client()
        if client is None:
            return

        payload = {
            "event_name": event_name,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "org_id": org_id,
            "user_id": user_id,
            "session_id": session_id,
            "properties": json.dumps(properties),
            "source": source,
            "ip": ip,
        }

        if _is_clickhouse():
            # ClickHouse HTTP interface: INSERT INTO events FORMAT JSONEachRow
            resp = await client.post(
                "/",
                params={"query": "INSERT INTO events FORMAT JSONEachRow"},
                json=payload,
            )
        else:
            # Tinybird Events API
            resp = await client.post(
                "/v0/events?name=events",
                json=payload,
            )

        if resp.status_code >= 500:
            logger.warning(
                "Analytics server error (%s): %s",
                resp.status_code,
                resp.text[:200],
            )
        elif resp.status_code >= 400:
            logger.error(
                "Analytics client error (%s) — check event payload: %s",
                resp.status_code,
                resp.text[:200],
            )
    except Exception:
        logger.warning("Failed to send analytics event %s", event_name, exc_info=True)
