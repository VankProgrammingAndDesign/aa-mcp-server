"""
Parser for Automation Anywhere A360 bot export ZIP packages.

A360 exports are ZIP files containing:
- Extensionless bot definition files (valid JSON with a "nodes" top-level key)
  under paths like: Automation Anywhere/Bots/.../BotName
- JAR files (Java command package implementations — skipped)
- PNG screenshots (Recorder capture images — skipped)
- manifest.json (file inventory with content types and dependencies)

This module is sync-only. Callers in tools/packages.py wrap with asyncio.to_thread().
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

logger = logging.getLogger(__name__)

_BOT_PATH_MARKER = "Automation Anywhere/Bots/"


def extract_package(zip_path: str) -> dict[str, Any]:
    """
    Open an A360 export ZIP and parse all bot definitions found inside.

    Raises FileNotFoundError if the path does not exist.
    Raises ValueError if the path is not a valid ZIP file.

    Returns a dict with keys: manifest, bots, parse_warnings, zip_summary.
    """
    p = Path(zip_path)
    if not p.exists():
        raise FileNotFoundError(f"Package not found: {zip_path}")
    if not zipfile.is_zipfile(p):
        raise ValueError(f"Not a valid ZIP file: {zip_path}")

    bots: dict[str, Any] = {}
    warnings: list[str] = []
    raw_manifest: dict[str, Any] = {}
    summary = {"total_files": 0, "bot_files": 0, "png_files": 0, "jar_files": 0}

    with zipfile.ZipFile(p, "r") as zf:
        entries = zf.infolist()
        summary["total_files"] = len(entries)

        for entry in entries:
            name = entry.filename
            # Normalize Windows-style backslashes (manifest uses them)
            name_norm = name.replace("\\", "/")

            if name_norm == "manifest.json":
                try:
                    raw_manifest = json.loads(
                        zf.read(entry).decode("utf-8", errors="replace")
                    )
                except Exception as exc:
                    warnings.append(f"Could not parse manifest.json: {exc}")
                continue

            if name_norm.endswith(".jar"):
                summary["jar_files"] += 1
                continue

            if name_norm.endswith(".png"):
                summary["png_files"] += 1
                continue

            if name_norm.endswith("/"):
                # Directory entry
                continue

            # Bot candidate: extensionless file under the Bots path
            filename = name_norm.split("/")[-1]
            if "." in filename:
                # Has an extension — not a bot definition file (e.g. .json BotInsight files)
                continue

            if _BOT_PATH_MARKER not in name_norm:
                continue

            summary["bot_files"] += 1
            try:
                raw_bytes = zf.read(entry)
                data = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            except Exception:
                # Not JSON — silently skip
                summary["bot_files"] -= 1
                continue

            if "nodes" not in data:
                # JSON but not a bot definition
                summary["bot_files"] -= 1
                continue

            bot = _parse_bot(data, name_norm)
            bot_name = bot["name"]

            # Handle name collisions
            if bot_name in bots:
                existing_folder = bots[bot_name]["folder_path"]
                new_folder = bot["folder_path"]
                suffix = new_folder.replace("/", "_").replace(" ", "")[-12:]
                new_key = f"{bot_name}_{suffix}"
                warnings.append(
                    f"Bot name collision: '{bot_name}' found in both "
                    f"'{existing_folder}' and '{new_folder}'. "
                    f"Second bot stored as '{new_key}'."
                )
                bots[new_key] = bot
            else:
                bots[bot_name] = bot

    manifest = _parse_manifest_meta(raw_manifest, zip_path, list(bots.keys()))

    return {
        "manifest": manifest,
        "bots": bots,
        "parse_warnings": warnings,
        "zip_summary": summary,
    }


def _parse_manifest_meta(
    raw: dict[str, Any], zip_path: str, bot_names: list[str]
) -> dict[str, Any]:
    """Extract useful metadata from manifest.json and the ZIP filename."""
    stem = Path(zip_path).stem  # e.g. Export.20260330_221720.ryan.vankerkvoorde@xerox.com
    parts = stem.split(".", 2)
    exported_by = parts[2] if len(parts) >= 3 else ""

    return {
        "package_name": stem,
        "exported_by": exported_by,
        "bot_names": bot_names,
        "file_count": len(raw.get("files", [])),
    }


def _parse_bot(data: dict[str, Any], source_path: str) -> dict[str, Any]:
    """Normalize a raw bot JSON dict into the canonical bot structure."""
    name = source_path.rstrip("/").split("/")[-1]

    # Extract folder path: everything between "Bots/" and the bot name
    folder_path = ""
    if _BOT_PATH_MARKER in source_path:
        after_bots = source_path.split(_BOT_PATH_MARKER, 1)[1]
        parts = after_bots.rsplit("/", 1)
        folder_path = parts[0] if len(parts) > 1 else ""

    variables = [_parse_variable(v) for v in data.get("variables", [])]

    counter = [0]
    actions = _flatten_nodes(data.get("nodes", []), depth=0, counter=counter)

    packages_used = [
        {"name": p.get("name", ""), "version": p.get("version", "")}
        for p in data.get("packages", [])
        if p.get("name")
    ]

    return {
        "_source_path": source_path,
        "_raw": data,
        "name": name,
        "folder_path": folder_path,
        "variables": variables,
        "packages_used": packages_used,
        "actions": actions,
    }


def _parse_variable(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw variable dict."""
    if raw.get("input"):
        scope = "input"
    elif raw.get("output"):
        scope = "output"
    elif raw.get("workItem"):
        scope = "workItem"
    else:
        scope = "local"

    return {
        "name": raw.get("name", ""),
        "type": raw.get("type", ""),
        "scope": scope,
        "default_value": _extract_default_value(raw.get("defaultValue")),
        "description": raw.get("description", ""),
        "input_required": raw.get("inputRequired", False),
        "read_only": raw.get("readOnly", False),
    }


def _flatten_nodes(
    nodes: list[dict[str, Any]],
    depth: int,
    counter: list[int],
) -> list[dict[str, Any]]:
    """
    Recursively flatten a node tree into an ordered list.
    counter is a mutable single-element list used as a shared index across recursion.
    """
    result = []
    for node in nodes:
        idx = counter[0]
        counter[0] += 1

        pkg = node.get("packageName", "")
        cmd = node.get("commandName", "")
        label = _extract_node_label(node)
        disabled = node.get("disabled", False)
        uid = node.get("uid", "")

        # Output variables from returnTo mapping
        output_vars: list[str] = _extract_output_vars(node)

        # Subtask path for TaskBot/runTask
        subtask_path = ""
        if pkg == "TaskBot" and cmd == "runTask":
            subtask_path = _extract_subtask_path(node)

        result.append({
            "index": idx,
            "depth": depth,
            "uid": uid,
            "package": pkg,
            "command": cmd,
            "label": label,
            "disabled": disabled,
            "output_variables": output_vars,
            "subtask_path": subtask_path,
            "attributes": node.get("attributes", []),
        })

        # Recurse into children (If body, Loop body, Step, etc.)
        children = node.get("children", [])
        if children:
            result.extend(_flatten_nodes(children, depth + 1, counter))

        # Recurse into branches (ErrorHandler catch blocks — each is a full node)
        for branch in node.get("branches", []):
            branch_children = branch.get("children", [])
            if branch_children:
                result.extend(_flatten_nodes(branch_children, depth + 1, counter))

    return result


def _extract_node_label(node: dict[str, Any]) -> str:
    """
    Extract a human-readable label for a node.
    Comment nodes: use the comment text.
    Step nodes: look for a title attribute.
    Others: use commandName.
    """
    pkg = node.get("packageName", "")
    cmd = node.get("commandName", "")
    attrs = node.get("attributes", [])

    if pkg == "Comment":
        for attr in attrs:
            val = attr.get("value", {})
            text = val.get("string", "").strip()
            if text:
                return text[:120]  # Truncate very long comments

    if pkg == "Step":
        for attr in attrs:
            if attr.get("name") in ("title", "label", "stepName"):
                val = attr.get("value", {})
                text = val.get("string", "").strip()
                if text:
                    return text

    return cmd or pkg


def _extract_output_vars(node: dict[str, Any]) -> list[str]:
    """
    Extract output variable name(s) from a node's returnTo field.

    A360 uses two formats:
    - returnTo.variableName (string) — most single-output commands (String.assign, etc.)
    - returnTo.dictionary  (list)   — multi-output commands (Database.select, etc.)
    """
    return_to = node.get("returnTo", {})
    if not isinstance(return_to, dict):
        return []

    # Multi-output: dictionary list with key entries
    raw_dict = return_to.get("dictionary", [])
    vars_from_dict = [e.get("key", "") for e in raw_dict if e.get("key")]
    if vars_from_dict:
        return vars_from_dict

    # Single-output: direct variableName string
    var_name = return_to.get("variableName", "")
    if var_name:
        return [var_name]

    return []


def _extract_subtask_path(node: dict[str, Any]) -> str:
    """Extract and decode the subtask file path from a TaskBot/runTask node."""
    for attr in node.get("attributes", []):
        if attr.get("name") == "taskbot":
            val = attr.get("value", {})
            taskbot_file = val.get("taskbotFile", {})
            raw_path = taskbot_file.get("string", "")
            if raw_path:
                # Remove repository:/// prefix and URL-decode
                cleaned = raw_path.replace("repository:///", "")
                return unquote(cleaned)
    return ""


def _extract_default_value(val: dict[str, Any] | None) -> Any:
    """Extract a simple Python value from a typed AA value dict."""
    if val is None:
        return None
    vtype = val.get("type", "")
    if vtype == "STRING":
        return val.get("string", "")
    if vtype == "NUMBER":
        raw = val.get("number", "")
        try:
            return float(raw) if "." in str(raw) else int(raw)
        except (ValueError, TypeError):
            return raw
    if vtype == "BOOLEAN":
        return str(val.get("boolean", "")).lower() == "true"
    # For complex types (LIST, DICTIONARY, etc.) return the raw dict
    return val


def build_structure(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build a nested hierarchical structure from raw bot nodes.
    Used by get_bot_structure — includes attributes for deep inspection.
    Public so tools/packages.py can call it.
    """
    result = []
    for node in nodes:
        pkg = node.get("packageName", "")
        cmd = node.get("commandName", "")

        entry: dict[str, Any] = {
            "uid": node.get("uid", ""),
            "package": pkg,
            "command": cmd,
            "label": _extract_node_label(node),
            "disabled": node.get("disabled", False),
            "attributes": node.get("attributes", []),
        }

        children = node.get("children", [])
        if children:
            entry["children"] = build_structure(children)

        branches = node.get("branches", [])
        if branches:
            entry["branches"] = [
                {
                    "package": b.get("packageName", ""),
                    "command": b.get("commandName", ""),
                    "children": build_structure(b.get("children", [])),
                }
                for b in branches
            ]

        if pkg == "TaskBot" and cmd == "runTask":
            entry["subtask_path"] = _extract_subtask_path(node)

        # Output variables — used by XAML generator for richer DisplayNames
        out_vars = _extract_output_vars(node)
        if out_vars:
            entry["output_variables"] = out_vars

        result.append(entry)

    return result
