from typing import Any

from aa_mcp.client import ControlRoomClient


async def list_queues(
    client: ControlRoomClient,
    name_filter: str | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "page": {"offset": 0, "length": 200},
    }
    if name_filter:
        body["filter"] = {
            "operator": "substring",
            "field": "name",
            "value": name_filter,
        }

    data = await client.post("/v2/wlm/queues/list", body)
    items = data.get("list", [])

    results = []
    for item in items:
        stats = item.get("workItemStatistics", {})
        results.append({
            "id": str(item.get("id", "")),
            "name": item.get("name", ""),
            "status": item.get("status", ""),
            "pending_count": stats.get("readyCount", 0),
            "in_progress_count": stats.get("inProgressCount", 0),
            "completed_count": stats.get("completedCount", 0),
            "failed_count": stats.get("failedCount", 0),
        })

    return results


async def get_queue_detail(
    client: ControlRoomClient,
    queue_id: str,
    status_filter: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "page": {"offset": 0, "length": limit},
    }
    if status_filter:
        body["filter"] = {
            "operator": "eq",
            "field": "status",
            "value": status_filter.upper(),
        }

    data = await client.post(f"/v2/wlm/queues/{queue_id}/workitems/list", body)
    items = data.get("list", [])
    total_available = data.get("page", {}).get("totalFilter", len(items))

    # Build status breakdown from returned items
    breakdown: dict[str, int] = {}
    for item in items:
        s = item.get("status", "UNKNOWN")
        breakdown[s] = breakdown.get(s, 0) + 1

    work_items = [
        {
            "id": str(item.get("id", "")),
            "status": item.get("status", ""),
            "created_at": item.get("createdOn", ""),
            "updated_at": item.get("updatedOn", ""),
            "error": item.get("comment") or None,
        }
        for item in items
    ]

    result: dict[str, Any] = {
        "queue_id": queue_id,
        "status_breakdown": breakdown,
        "total_returned": len(work_items),
        "total_available": total_available,
        "truncated": total_available > limit,
    }
    if not result["truncated"]:
        result["items"] = work_items

    return result
