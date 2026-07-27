"""
UiPath project writer.

Orchestrates the full AA → UiPath conversion pipeline:
  1. Parse the AA export ZIP
  2. Build a ProcessSummary via mapper
  3. Generate XAML via xaml module
  4. Write project.json + .xaml files to the output directory

Entry point: generate_project_files()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from aa_mcp import package_parser
from aa_mcp.uipath import docgen, mapper, xaml
from aa_mcp.uipath.mapper import PARTIAL, TODO, sanitize_filename

logger = logging.getLogger(__name__)

_LARGE_BOT_STEP_THRESHOLD = 200


# ── Public entry point ─────────────────────────────────────────────────────────

async def generate_project_files(
    zip_path: str,
    bot_name: str,
    output_path: str,
) -> dict[str, Any]:
    """
    Full pipeline: parse → summarize → generate XAML → write to disk.

    Parameters
    ----------
    zip_path:    Absolute path to the AA A360 export ZIP.
    bot_name:    Exact bot name as returned by load_bot_package.
    output_path: Directory to write the UiPath project into (created if absent).

    Returns a generation report dict.
    """
    # 1. Parse the package
    contents = await asyncio.to_thread(package_parser.extract_package, zip_path)

    # 2. Find the master bot
    master_bot = _get_bot(contents, bot_name)
    if "error" in master_bot:
        return master_bot

    all_bots = contents["bots"]

    # 3. Build process summary
    summary = await asyncio.to_thread(
        mapper.build_process_summary, master_bot, all_bots
    )
    all_summaries: dict[str, Any] = {bot_name: summary}

    # 4. Build structured node tree for XAML generation
    raw_nodes = master_bot["_raw"].get("nodes", [])
    structured_nodes = await asyncio.to_thread(
        package_parser.build_structure, raw_nodes
    )

    # 5. Generate main XAML
    main_filename = sanitize_filename(bot_name) + ".xaml"
    main_xaml = xaml.generate_workflow_xaml(summary, bot_name, structured_nodes)

    # 6. Generate sub-bot XAMLs (BFS — recurses into sub-bots of sub-bots)
    files: dict[str, str] = {main_filename: main_xaml}
    sub_bots_generated: list[str] = []
    sub_bots_stubbed: list[str] = []
    processed_xaml: set[str] = set()  # guards against circular references

    queue: list[dict[str, Any]] = list(summary.get("sub_bots_called", []))
    while queue:
        sub = queue.pop(0)
        xaml_filename = sub["xaml_filename"]

        if xaml_filename in processed_xaml:
            continue
        processed_xaml.add(xaml_filename)

        resolved_name = sub["resolved_bot_name"]

        if resolved_name and resolved_name in all_bots:
            sub_bot = all_bots[resolved_name]
            sub_summary = await asyncio.to_thread(
                mapper.build_process_summary, sub_bot, all_bots
            )
            sub_raw = sub_bot["_raw"].get("nodes", [])
            sub_structured = await asyncio.to_thread(
                package_parser.build_structure, sub_raw
            )
            sub_xaml_content = xaml.generate_workflow_xaml(
                sub_summary, resolved_name, sub_structured
            )
            files[xaml_filename] = sub_xaml_content
            sub_bots_generated.append(xaml_filename)
            all_summaries[resolved_name] = sub_summary
            # Enqueue this sub-bot's own sub-bots
            queue.extend(sub_summary.get("sub_bots_called", []))
        else:
            # Bot not in package — generate a stub
            stub_summary: dict[str, Any] = {
                "variables": [],
                "error_handling": {"detected": False, "pattern": "None"},
            }
            stub_content = xaml.generate_workflow_xaml(
                stub_summary,
                sub["subtask_path"].rstrip("/").split("/")[-1],
                [],
                is_stub=True,
            )
            files[xaml_filename] = stub_content
            sub_bots_stubbed.append(xaml_filename)

    # 7. Build project.json
    project_json = _build_project_json(summary, main_filename, bot_name)
    files["project.json"] = json.dumps(project_json, indent=2)

    # 7b. Generate documentation
    files["PDD.md"] = await asyncio.to_thread(docgen.generate_pdd, summary)
    files["ARCHITECTURE.md"] = await asyncio.to_thread(
        docgen.generate_architecture_doc,
        summary, all_summaries, sub_bots_generated, sub_bots_stubbed,
    )

    # 8. Write all files to disk
    await asyncio.to_thread(_write_files, output_path, files)

    # 9. Build manual review notes
    review_notes = _build_review_notes(summary)

    # 10. Large-bot warning
    warnings: list[str] = []
    total_steps = summary["stats"]["total_steps"]
    if total_steps > _LARGE_BOT_STEP_THRESHOLD:
        warnings.append(
            f"Bot has {total_steps} steps (>{_LARGE_BOT_STEP_THRESHOLD}). "
            "Consider splitting into smaller workflows in Studio."
        )

    return {
        "output_path": str(Path(output_path).resolve()),
        "files_written": sorted(files.keys()),
        "main_xaml": main_filename,
        "sub_bots_generated": sub_bots_generated,
        "sub_bots_stubbed": sub_bots_stubbed,
        "summary": summary,
        "manual_review_notes": review_notes,
        "warnings": warnings,
    }


# ── project.json builder ───────────────────────────────────────────────────────

def _build_project_json(
    summary: dict[str, Any],
    main_xaml_filename: str,
    bot_name: str,
) -> dict[str, Any]:
    """Build a valid UiPath project.json manifest."""
    stats = summary.get("stats", {})
    coverage = stats.get("coverage_pct", 0.0)
    total = stats.get("total_steps", 0)
    description = (
        f"Converted from AA bot '{bot_name}'. "
        f"{total} steps ({coverage}% mapped). "
        "Review [PARTIAL] and [TODO] items before execution."
    )

    # Collect dependencies from nuget_packages
    nuget = summary.get("nuget_packages", [])
    dependencies = {
        pkg["name"]: f"[{pkg['version']}]"
        for pkg in nuget
    }
    # Always include System.Activities
    if "UiPath.System.Activities" not in dependencies:
        version = mapper.NUGET_VERSIONS["UiPath.System.Activities"]
        dependencies["UiPath.System.Activities"] = f"[{version}]"

    # Entry point arguments from input/output variables
    entry_inputs = [
        {"name": v["name"], "type": v["uipath_type"], "required": v["input_required"]}
        for v in summary.get("variables", [])
        if v.get("uipath_direction") == "In"
    ]
    entry_outputs = [
        {"name": v["name"], "type": v["uipath_type"]}
        for v in summary.get("variables", [])
        if v.get("uipath_direction") == "Out"
    ]

    return {
        "schemaVersion": "1.0",
        "name": sanitize_filename(bot_name),
        "description": description,
        "projectVersion": "1.0.0",
        "studioVersion": "24.10.0.0",
        "projectType": "Process",
        "main": main_xaml_filename,
        "outputType": "Process",
        "designOptions": {
            "outputType": "Process",
            "resumeOnSameContext": False,
            "pauseActivityScheduling": False,
        },
        "dependencies": dependencies,
        "entryPoints": [
            {
                "filePath": main_xaml_filename,
                "input": entry_inputs,
                "output": entry_outputs,
            }
        ],
        "expressionLanguage": "VisualBasic",
        "targetFramework": "Windows",
        "runtimeOptions": {
            "requiresUserInteraction": False,
        },
    }


# ── File I/O ───────────────────────────────────────────────────────────────────

def _write_files(output_path: str, files: dict[str, str]) -> None:
    """Write all generated file content to disk under output_path."""
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        dest = out / filename
        dest.write_text(content, encoding="utf-8")
        logger.debug("Wrote %s (%d bytes)", dest, len(content))


# ── Manual review notes ────────────────────────────────────────────────────────

def _build_review_notes(summary: dict[str, Any]) -> list[str]:
    """Build a flat list of review notes for every PARTIAL and TODO step."""
    notes: list[str] = []
    for step in summary.get("steps", []):
        status = step.get("mapping_status")
        if status not in (PARTIAL, TODO):
            continue
        if step.get("disabled"):
            continue
        tag = "[PARTIAL]" if status == PARTIAL else "[TODO]"
        label = step.get("label", "")
        pkg = step.get("aa_package", "")
        cmd = step.get("aa_command", "")
        activity = step.get("uipath_activity", "")
        notes_text = step.get("mapping_notes", "")
        notes.append(
            f"Step {step['index']}: {tag} {label}"
            f" | AA: {pkg}.{cmd}"
            f" → UiPath: {activity}"
            f" | {notes_text}"
        )
    return notes


# ── Bot lookup helper ──────────────────────────────────────────────────────────

def _get_bot(contents: dict[str, Any], bot_name: str) -> dict[str, Any]:
    """Case-insensitive bot lookup. Returns an error dict if not found."""
    bots = contents.get("bots", {})
    name_lower = bot_name.lower()
    for key, bot in bots.items():
        if key.lower() == name_lower:
            return bot
    return {"error": f"Bot '{bot_name}' not found. Available: {list(bots.keys())}"}
