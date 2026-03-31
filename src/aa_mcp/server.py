import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from aa_mcp.auth import AuthClient
from aa_mcp.client import ControlRoomClient
from aa_mcp.models.config import get_settings
from aa_mcp.tools import activity, bots, packages, wlm

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
    http = httpx.AsyncClient(timeout=settings.http_timeout_seconds, verify=settings.ssl_verify)
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
    Returns id, hostname, status, pool, default_user_id, and default_username for each device.
    Use default_user_id as the run_as_user_id when calling deploy_bot.
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
    List WLM queues. Returns id, name, status, and description for each queue.
    Use get_queue_detail to get item counts and work item status breakdown for a specific queue.
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


@mcp.tool()
async def load_bot_package(zip_path: str) -> dict[str, Any]:
    """
    Load and summarize an Automation Anywhere A360 bot export ZIP file.
    zip_path: absolute path to a local .zip export file from Control Room.
    Returns manifest metadata, bot names found, packages in use, and a file count summary.
    Call this first before using list_bot_actions, get_bot_variables, get_bot_structure, or search_bot_actions.
    """
    return await packages.load_bot_package(zip_path)


@mcp.tool()
async def list_bot_actions(zip_path: str, bot_name: str) -> dict[str, Any]:
    """
    List all action nodes in a bot in execution order, including nested actions with depth.
    zip_path: path to the export ZIP. bot_name: exact name from load_bot_package.
    Returns package, command, label, depth, uid, output_variables, and subtask_path for each action.
    TaskBot/runTask actions include subtask_path showing which subtask is called.
    Use get_bot_structure for full nested hierarchy with action attributes.
    """
    return await packages.list_bot_actions(zip_path, bot_name)


@mcp.tool()
async def get_bot_variables(zip_path: str, bot_name: str) -> dict[str, Any]:
    """
    Get all variables defined in a bot with types, scope, and default values.
    zip_path: path to the export ZIP. bot_name: exact name from load_bot_package.
    Returns a variable list plus by_type and by_scope indexes for quick lookup.
    Scope values: input, output, workItem, local.
    """
    return await packages.get_bot_variables(zip_path, bot_name)


@mcp.tool()
async def get_bot_structure(zip_path: str, bot_name: str) -> dict[str, Any]:
    """
    Get the full nested action structure of a bot including all attributes and branches.
    zip_path: path to the export ZIP. bot_name: exact name from load_bot_package.
    Returns a nested tree with action attributes for deep inspection of what each action does.
    branches contain ErrorHandler catch blocks. Use list_bot_actions for a flat overview instead.
    """
    return await packages.get_bot_structure(zip_path, bot_name)


@mcp.tool()
async def search_bot_actions(zip_path: str, action_type: str) -> dict[str, Any]:
    """
    Search all bots in a package for actions matching a package or command name.
    zip_path: path to the export ZIP. action_type: substring matched case-insensitively.
    Examples: "Recorder" (screen captures), "TaskBot" (subtask calls), "Database",
    "Email", "Excel", "REST", "Loop", "If".
    Returns matches across all bots with bot name, position, and action details.
    """
    return await packages.search_bot_actions(zip_path, action_type)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
