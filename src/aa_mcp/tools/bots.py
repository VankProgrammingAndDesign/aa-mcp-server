from typing import Any

from aa_mcp.client import ControlRoomClient

_BOT_TYPE = "application/vnd.aa.taskbot"


async def list_bots(client: ControlRoomClient, name_filter: str | None = None) -> list[dict[str, Any]]:
    page_size = 100
    results: list[dict[str, Any]] = []

    # Build filter — always restrict to task bots; optionally add name substring
    type_filter: dict[str, Any] = {"operator": "eq", "field": "type", "value": _BOT_TYPE}
    if name_filter:
        combined_filter: dict[str, Any] = {
            "operator": "and",
            "operands": [
                type_filter,
                {"operator": "substring", "field": "name", "value": name_filter},
            ],
        }
    else:
        combined_filter = type_filter

    while True:
        body: dict[str, Any] = {
            "page": {"offset": len(results), "length": page_size},
            "filter": combined_filter,
        }
        data = await client.post("/v2/repository/workspaces/public/files/list", body)
        items = data.get("list", [])
        for item in items:
            results.append({
                "id": str(item.get("id", "")),
                "name": item.get("name", ""),
                "path": item.get("path", ""),
                "last_modified": item.get("lastModified"),
            })

        total = data.get("page", {}).get("totalFilter", len(results))
        if len(results) >= total or not items:
            break

    return results


async def list_devices(client: ControlRoomClient, name_filter: str | None = None) -> list[dict[str, Any]]:
    data = await client.post("/v2/devices/list", {"page": {"offset": 0, "length": 200}})
    items = data.get("list", [])

    results = []
    for item in items:
        hostname = item.get("hostName", "")
        if name_filter and name_filter.lower() not in hostname.lower():
            continue
        # defaultUsers contains the run-as credentials — expose the first user's id
        default_users = item.get("defaultUsers", [])
        default_user = default_users[0] if default_users else {}
        results.append({
            "id": str(item.get("id", "")),
            "hostname": hostname,
            "status": item.get("status", ""),
            "pool": item.get("poolName", ""),
            "default_user_id": str(default_user.get("id", "")),
            "default_username": default_user.get("username", ""),
        })

    return results


async def deploy_bot(
    client: ControlRoomClient,
    bot_id: str,
    device_id: str,
    run_as_user_id: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "fileId": int(bot_id),
        "botInput": {},
        "runAsUserIds": [int(run_as_user_id)],
        "currentUserDeviceCredentialMappings": [
            {
                "userId": int(run_as_user_id),
                "credentialType": "DEVICE",
                "deviceCredentials": [{"deviceId": int(device_id)}],
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
