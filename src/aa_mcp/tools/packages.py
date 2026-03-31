"""
MCP tools for analyzing Automation Anywhere A360 bot export packages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aa_mcp import package_parser

logger = logging.getLogger(__name__)


def _get_bot(contents: dict[str, Any], bot_name: str) -> dict[str, Any] | None:
    """
    Case-insensitive lookup of a bot by name in extracted package contents.
    Returns the bot dict, or an error dict if not found.
    """
    bots = contents.get("bots", {})
    name_lower = bot_name.lower()
    for key, bot in bots.items():
        if key.lower() == name_lower:
            return bot
    available = list(bots.keys())
    return {"error": f"Bot '{bot_name}' not found. Available: {available}"}


async def load_bot_package(zip_path: str) -> dict[str, Any]:
    """Load and summarize an A360 export ZIP package."""
    try:
        contents = await asyncio.to_thread(package_parser.extract_package, zip_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "zip_path": zip_path}

    # Collect packages_in_use across all bots (deduplicated by name)
    seen_pkgs: dict[str, str] = {}
    for bot in contents["bots"].values():
        for pkg in bot.get("packages_used", []):
            name = pkg.get("name", "")
            if name and name not in seen_pkgs:
                seen_pkgs[name] = pkg.get("version", "")

    packages_in_use = [
        {"name": name, "version": version} for name, version in sorted(seen_pkgs.items())
    ]

    bots = contents["bots"]
    bot_names = list(bots.keys())

    return {
        "zip_path": zip_path,
        "manifest": contents["manifest"],
        "bot_count": len(bot_names),
        "bot_names": bot_names,
        "packages_in_use": packages_in_use,
        "parse_warnings": contents["parse_warnings"],
        "zip_summary": contents["zip_summary"],
    }


async def list_bot_actions(zip_path: str, bot_name: str) -> dict[str, Any]:
    """List all action nodes in a bot in execution order."""
    try:
        contents = await asyncio.to_thread(package_parser.extract_package, zip_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "zip_path": zip_path}

    bot = _get_bot(contents, bot_name)
    if "error" in bot:
        return bot

    actions = bot.get("actions", [])

    # Strip verbose attributes from the list view — available in get_bot_structure
    slim_actions = [
        {
            "index": a["index"],
            "depth": a["depth"],
            "package": a["package"],
            "command": a["command"],
            "label": a["label"],
            "disabled": a["disabled"],
            "uid": a["uid"],
            "output_variables": a["output_variables"],
            "subtask_path": a["subtask_path"],
        }
        for a in actions
    ]

    return {
        "bot_name": bot["name"],
        "folder_path": bot["folder_path"],
        "action_count": len(slim_actions),
        "actions": slim_actions,
    }


async def get_bot_variables(zip_path: str, bot_name: str) -> dict[str, Any]:
    """Get all variables defined in a bot with types and default values."""
    try:
        contents = await asyncio.to_thread(package_parser.extract_package, zip_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "zip_path": zip_path}

    bot = _get_bot(contents, bot_name)
    if "error" in bot:
        return bot

    variables = bot.get("variables", [])

    by_type: dict[str, list[str]] = {}
    by_scope: dict[str, list[str]] = {}
    for v in variables:
        vtype = v.get("type", "UNKNOWN")
        scope = v.get("scope", "local")
        name = v.get("name", "")
        by_type.setdefault(vtype, []).append(name)
        by_scope.setdefault(scope, []).append(name)

    return {
        "bot_name": bot["name"],
        "variable_count": len(variables),
        "variables": variables,
        "by_type": by_type,
        "by_scope": by_scope,
    }


async def get_bot_structure(zip_path: str, bot_name: str) -> dict[str, Any]:
    """Get the full nested action structure of a bot including attributes."""
    try:
        contents = await asyncio.to_thread(package_parser.extract_package, zip_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "zip_path": zip_path}

    bot = _get_bot(contents, bot_name)
    if "error" in bot:
        return bot

    raw_nodes = bot["_raw"].get("nodes", [])
    structure = await asyncio.to_thread(package_parser.build_structure, raw_nodes)

    return {
        "bot_name": bot["name"],
        "folder_path": bot["folder_path"],
        "structure": structure,
    }


async def search_bot_actions(zip_path: str, action_type: str) -> dict[str, Any]:
    """Search all bots in a package for actions matching a package or command name."""
    try:
        contents = await asyncio.to_thread(package_parser.extract_package, zip_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "zip_path": zip_path}

    term = action_type.lower()
    matches: list[dict[str, Any]] = []

    for bot_name, bot in contents["bots"].items():
        for action in bot.get("actions", []):
            pkg = action.get("package", "").lower()
            cmd = action.get("command", "").lower()
            if term in pkg or term in cmd:
                matches.append({
                    "bot_name": bot_name,
                    "action_index": action["index"],
                    "depth": action["depth"],
                    "package": action["package"],
                    "command": action["command"],
                    "label": action["label"],
                    "uid": action["uid"],
                    "disabled": action["disabled"],
                    "subtask_path": action["subtask_path"],
                })

    return {
        "search_term": action_type,
        "total_matches": len(matches),
        "matches": matches,
    }
