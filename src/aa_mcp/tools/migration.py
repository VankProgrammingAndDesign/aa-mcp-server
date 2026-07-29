"""
MCP tools for converting Automation Anywhere bots to UiPath project templates.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aa_mcp import package_parser
from aa_mcp.uipath import docgen, mapper, writer

logger = logging.getLogger(__name__)


def _get_bot(contents: dict[str, Any], bot_name: str) -> dict[str, Any]:
    """Case-insensitive lookup of a bot by name. Returns an error dict if not found."""
    bots = contents.get("bots", {})
    name_lower = bot_name.lower()
    for key, bot in bots.items():
        if key.lower() == name_lower:
            return bot
    return {"error": f"Bot '{bot_name}' not found. Available: {list(bots.keys())}"}


async def summarize_bot_process(
    zip_path: str,
    bot_name: str,
) -> dict[str, Any]:
    """
    Parse an AA bot and return a structured process summary for UiPath migration.

    Returns variable mappings with UiPath argument types, step-by-step activity
    mappings with status (mapped/partial/todo), sub-bots called, error handling
    pattern, external systems, required NuGet packages, and coverage stats.

    Call this before generate_uipath_template to inspect the mapping first.
    """
    try:
        contents = await asyncio.to_thread(package_parser.extract_package, zip_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "zip_path": zip_path}

    bot = _get_bot(contents, bot_name)
    if "error" in bot:
        return bot

    result = await asyncio.to_thread(
        mapper.build_process_summary, bot, contents["bots"]
    )

    # Add in-memory documentation (single-bot view; no recursive BFS here)
    pdd = await asyncio.to_thread(docgen.generate_pdd, result)
    arch = await asyncio.to_thread(
        docgen.generate_architecture_doc,
        result, {result["bot_name"]: result}, [], [],
    )
    result["documentation"] = {"pdd": pdd, "architecture_overview": arch}
    return result


async def generate_uipath_template(
    zip_path: str,
    bot_name: str,
    output_path: str,
    reference_project: str | None = None,
    package_versions: dict[str, str] | None = None,
    version_constraint: str = "exact",
) -> dict[str, Any]:
    """
    Convert an AA bot to a complete UiPath project folder ready to open in Studio.

    Writes to output_path:
    - project.json with correct NuGet dependencies
    - {bot_name}.xaml primary workflow with WF4 activities
    - One .xaml file per direct sub-bot (full workflow if present in ZIP, stub if not)

    Mapped steps get real WF4 activities (InvokeWorkflowFile, TryCatch, ForEach, If).
    Partial/unmapped steps become named [PARTIAL] or [TODO] Sequence placeholders.

    Optional inputs to match the target Studio environment:
    - reference_project: path to a real Studio project.json (a file, a project
      folder, or a .zip); its dependency versions, studioVersion, and
      schemaVersion are mirrored.
    - package_versions: explicit {package: version} pins (highest precedence).
    - version_constraint: 'exact' ([x], default) or 'minimum' ([x, )).

    Returns a generation report with files written, coverage stats, and manual review
    notes listing every step that needs attention in Studio.
    """
    try:
        return await writer.generate_project_files(
            zip_path, bot_name, output_path,
            reference_project=reference_project,
            package_versions=package_versions,
            version_constraint=version_constraint,
        )
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc), "zip_path": zip_path}
    except OSError as exc:
        return {"error": f"Failed to write output: {exc}", "output_path": output_path}
