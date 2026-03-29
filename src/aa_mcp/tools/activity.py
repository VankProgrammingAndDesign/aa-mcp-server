from datetime import datetime, timezone
from typing import Any

from aa_mcp.client import ControlRoomClient


def _duration_seconds(started: str, ended: str | None) -> int | None:
    if not started or not ended:
        return None
    try:
        fmt = "%Y-%m-%dT%H:%M:%S%z"
        start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        return max(0, int((end_dt - start_dt).total_seconds()))
    except Exception:
        return None


async def list_running_automations(
    client: ControlRoomClient,
    limit: int = 50,
) -> list[dict[str, Any]]:
    data = await client.get(
        "/v2/activity/list",
        params={"status": "RUNNING", "limit": limit},
    )
    items = data.get("list", [])
    return [
        {
            "activity_id": str(item.get("id", "")),
            "bot_name": item.get("automationName", ""),
            "device_hostname": item.get("deviceName", ""),
            "started_at": item.get("startDateTime", ""),
            "status": item.get("status", "RUNNING"),
        }
        for item in items
    ]


async def list_run_history(
    client: ControlRoomClient,
    bot_name_filter: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []

    if bot_name_filter:
        filters.append({
            "operator": "substring",
            "field": "automationName",
            "value": bot_name_filter,
        })
    if status:
        filters.append({
            "operator": "eq",
            "field": "status",
            "value": status.upper(),
        })
    if start_date:
        filters.append({
            "operator": "gte",
            "field": "startDateTime",
            "value": start_date,
        })
    if end_date:
        filters.append({
            "operator": "lte",
            "field": "startDateTime",
            "value": end_date,
        })

    body: dict[str, Any] = {
        "page": {"offset": 0, "length": limit},
        "sort": [{"field": "startDateTime", "direction": "desc"}],
    }
    if len(filters) == 1:
        body["filter"] = filters[0]
    elif len(filters) > 1:
        body["filter"] = {"operator": "and", "operands": filters}

    data = await client.post("/v2/activity/list", body)
    items = data.get("list", [])

    results = []
    for item in items:
        started = item.get("startDateTime", "")
        ended = item.get("endDateTime")
        results.append({
            "activity_id": str(item.get("id", "")),
            "bot_name": item.get("automationName", ""),
            "device_hostname": item.get("deviceName", ""),
            "started_at": started,
            "ended_at": ended,
            "duration_seconds": _duration_seconds(started, ended),
            "status": item.get("status", ""),
            "error_message": item.get("message") or None,
        })

    return results
