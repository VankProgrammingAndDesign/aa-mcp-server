from typing import Any

from aa_mcp.client import ControlRoomClient


async def list_bots(client: ControlRoomClient, name_filter: str | None = None) -> list[dict[str, Any]]:
    page = 1
    page_size = 100
    results: list[dict[str, Any]] = []

    while True:
        body: dict[str, Any] = {
            "page": {"offset": (page - 1) * page_size, "length": page_size},
        }
        if name_filter:
            body["filter"] = {
                "operator": "substring",
                "field": "name",
                "value": name_filter,
            }

        data = await client.post("/v3/automations/list", body)
        items = data.get("list", [])
        for item in items:
            results.append({
                "id": str(item.get("id", "")),
                "name": item.get("name", ""),
                "folder_path": item.get("path", ""),
                "type": item.get("type", ""),
                "last_modified": item.get("lastModifiedBy", {}).get("lastModifiedDate"),
            })

        total = data.get("page", {}).get("totalFilter", len(results))
        if len(results) >= total or not items:
            break
        page += 1

    return results


async def list_devices(client: ControlRoomClient, name_filter: str | None = None) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "page": {"offset": 0, "length": 200},
        "filter": {
            "operator": "eq",
            "field": "type",
            "value": "BOT_RUNNER",
        },
    }

    data = await client.post("/v2/devices/list", body)
    items = data.get("list", [])

    results = []
    for item in items:
        hostname = item.get("hostName", "")
        if name_filter and name_filter.lower() not in hostname.lower():
            continue
        results.append({
            "id": str(item.get("id", "")),
            "hostname": hostname,
            "status": item.get("status", ""),
            "username": item.get("defaultUser", {}).get("username", ""),
        })

    return results


async def deploy_bot(
    client: ControlRoomClient,
    bot_id: str,
    device_id: str,
    run_as_user_id: str,
) -> dict[str, Any]:
    body = {
        "fileId": int(bot_id),
        "botInput": {},
        "currentUserDeviceCredentialMappings": [
            {
                "deviceId": int(device_id),
                "runAsUserIds": [int(run_as_user_id)],
            }
        ],
        "scheduleType": "INSTANT",
    }

    data = await client.post("/v3/automations/deploy", body)
    return {
        "deployment_id": str(data.get("deploymentId", "")),
        "status": data.get("status", "QUEUED"),
        "queued_at": data.get("startTime", ""),
    }
