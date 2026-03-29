import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from aa_mcp.auth import AuthClient
from aa_mcp.client import ControlRoomClient
from aa_mcp.models.config import get_settings
from aa_mcp.tools import activity, bots, wlm

settings = get_settings()

logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, settings.log_level.upper(), logging.WARNING),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

_client: ControlRoomClient | None = None


@asynccontextmanager
async def lifespan(app: FastMCP):
    global _client
    auth = AuthClient(settings)
    http = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    _client = ControlRoomClient(settings, auth, http)
    try:
        yield
    finally:
        await http.aclose()


mcp = FastMCP("aa-mcp-server", lifespan=lifespan)


def get_client() -> ControlRoomClient:
    if _client is None:
        raise RuntimeError("Client not initialized — server lifespan may not have started")
    return _client


@mcp.tool()
async def list_bots(name_filter: str | None = None) -> list[dict[str, Any]]:
    """
    List bots available in the Control Room.
    Use name_filter to search by substring (case-insensitive).
    Returns id, name, folder_path, and type for each bot.
    Call this first when you need a bot_id for deploy_bot.
    """
    return await bots.list_bots(get_client(), name_filter=name_filter)


@mcp.tool()
async def list_devices(name_filter: str | None = None) -> list[dict[str, Any]]:
    """
    List bot runner devices registered in the Control Room.
    Use name_filter to search by hostname substring.
    Returns id, hostname, status, and username for each device.
    Call this first when you need a device_id for deploy_bot.
    """
    return await bots.list_devices(get_client(), name_filter=name_filter)


@mcp.tool()
async def deploy_bot(bot_id: str, device_id: str, run_as_user_id: str) -> dict[str, Any]:
    """
    Deploy a bot to a specific device and run it immediately.
    Use list_bots to find bot_id and list_devices to find device_id.
    run_as_user_id is the numeric user ID for the runner credential.
    Returns deployment_id and queued status.
    """
    return await bots.deploy_bot(
        get_client(), bot_id=bot_id, device_id=device_id, run_as_user_id=run_as_user_id
    )


@mcp.tool()
async def list_running_automations(limit: int = 50) -> list[dict[str, Any]]:
    """
    List automations currently running in the Control Room.
    Returns activity_id, bot_name, device_hostname, and started_at for each active run.
    Returns an empty list if nothing is running.
    """
    return await activity.list_running_automations(get_client(), limit=limit)


@mcp.tool()
async def list_run_history(
    bot_name_filter: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    List historical automation runs, sorted newest first.
    bot_name_filter: substring match on bot name.
    status: COMPLETED, FAILED, STOPPED, or TIMED_OUT.
    start_date / end_date: ISO 8601, e.g. "2026-03-01T00:00:00Z".
    Returns activity_id, bot_name, status, duration_seconds, and error_message.
    """
    return await activity.list_run_history(
        get_client(),
        bot_name_filter=bot_name_filter,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@mcp.tool()
async def list_queues(name_filter: str | None = None) -> list[dict[str, Any]]:
    """
    List WLM queues with item counts by status.
    Returns id, name, status, and counts: pending, in_progress, completed, failed.
    Use queue id with get_queue_detail to inspect individual work items.
    Requires AAE_Queue Admin role on the service account.
    """
    return await wlm.list_queues(get_client(), name_filter=name_filter)


@mcp.tool()
async def get_queue_detail(
    queue_id: str,
    status_filter: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """
    Get work items for a specific WLM queue.
    queue_id: from list_queues.
    status_filter: NEW, IN_PROGRESS, COMPLETED, or FAILED.
    Returns status_breakdown counts and individual items up to limit.
    If truncated is true, add status_filter or reduce limit to see items.
    """
    return await wlm.get_queue_detail(
        get_client(), queue_id=queue_id, status_filter=status_filter, limit=limit
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
