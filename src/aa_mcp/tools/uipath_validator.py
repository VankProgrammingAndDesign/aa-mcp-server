"""
Structural validator for generated UiPath project folders.

Checks performed:
  1. output_path is an existing directory
  2. project.json exists and is valid JSON
  3. Required project.json keys present: name, main, schemaVersion, dependencies
  4. Main XAML file referenced in project.json exists on disk
  5. Every .xaml file is well-formed XML
  6. Every .xaml root element is <Activity>
  7. Every .xaml root has an x:Class attribute
  8. Every WorkflowFileName in InvokeWorkflowFile elements resolves to a file in the directory

Does not require UiPath Studio or any network access.
"""

from __future__ import annotations

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_NS_UI      = "http://schemas.uipath.com/workflow/activities"
_NS_XAML    = "http://schemas.microsoft.com/winfx/2006/xaml"
_INVOKE_TAG = f"{{{_NS_UI}}}InvokeWorkflowFile"
_X_CLASS    = f"{{{_NS_XAML}}}Class"

_REQUIRED_PROJECT_KEYS = ("name", "main", "schemaVersion", "dependencies")


# ── Public entry point ─────────────────────────────────────────────────────────

async def validate_uipath_project(output_path: str) -> dict[str, Any]:
    """
    Validate a generated UiPath project folder without UiPath Studio.

    output_path: directory written by generate_uipath_template.
    Returns a report with valid (bool), errors, warnings, files_checked,
    and broken_references (InvokeWorkflowFile targets missing from disk).
    """
    return await asyncio.to_thread(_validate, output_path)


# ── Sync implementation ────────────────────────────────────────────────────────

def _validate(output_path: str) -> dict[str, Any]:
    errors:       list[str] = []
    warnings:     list[str] = []
    broken_refs:  list[dict[str, str]] = []
    files_checked: list[str] = []
    project:      dict[str, Any] = {}

    directory = Path(output_path)

    # Check 1: directory exists
    if not directory.exists() or not directory.is_dir():
        errors.append(f"Directory not found: {output_path}")
        return _result(output_path, project, files_checked, errors, warnings, broken_refs)

    # Checks 2–5: project.json
    project = _check_project_json(directory, errors, warnings)

    # Checks 6–9: XAML files
    if not errors:  # skip XAML checks if project.json is broken
        files_checked = _check_xaml_files(directory, project, errors, warnings, broken_refs)

    return _result(output_path, project, files_checked, errors, warnings, broken_refs)


def _check_project_json(
    directory: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Parse and validate project.json. Returns parsed dict (empty on failure)."""
    pj = directory / "project.json"

    if not pj.exists():
        errors.append("project.json not found")
        return {}

    try:
        project = json.loads(pj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"project.json is not valid JSON: {exc}")
        return {}

    # Required keys
    for key in _REQUIRED_PROJECT_KEYS:
        if key not in project:
            errors.append(f"project.json missing required key: '{key}'")

    # Main XAML exists
    main = project.get("main", "")
    if main and not (directory / main).exists():
        errors.append(f"Main workflow file not found: {main}")

    # entryPoints cross-check (warning only)
    for ep in project.get("entryPoints", []):
        fp = ep.get("filePath", "")
        if fp and not (directory / fp).exists():
            warnings.append(f"entryPoints filePath not found: {fp}")

    return project


def _check_xaml_files(
    directory: Path,
    project: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    broken_refs: list[dict[str, str]],
) -> list[str]:
    """Validate all .xaml files. Returns list of filenames checked."""
    xaml_files = sorted(directory.glob("*.xaml"))
    checked: list[str] = []

    for xaml_path in xaml_files:
        fname = xaml_path.name
        checked.append(fname)

        # Check 6: well-formed XML
        try:
            tree = ET.parse(xaml_path)
        except ET.ParseError as exc:
            errors.append(f"{fname}: XML parse error — {exc}")
            continue

        root = tree.getroot()

        # Check 7: root element is Activity (any namespace)
        local_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if local_name != "Activity":
            warnings.append(f"{fname}: root element is <{local_name}>, expected <Activity>")

        # Check 8: x:Class attribute present
        if _X_CLASS not in root.attrib:
            warnings.append(f"{fname}: missing x:Class attribute on root element")

        # Check 9: InvokeWorkflowFile references
        for elem in tree.iter(_INVOKE_TAG):
            target = elem.get("WorkflowFileName", "")
            if target and not (directory / target).exists():
                broken_refs.append({"source_file": fname, "missing_target": target})
                errors.append(
                    f"{fname}: broken InvokeWorkflowFile reference → '{target}'"
                )

    return checked


def _result(
    output_path: str,
    project: dict[str, Any],
    files_checked: list[str],
    errors: list[str],
    warnings: list[str],
    broken_refs: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "valid":             len(errors) == 0,
        "output_path":       str(Path(output_path).resolve()),
        "project_name":      project.get("name", ""),
        "main_workflow":     project.get("main", ""),
        "dependency_count":  len(project.get("dependencies", {})),
        "files_checked":     files_checked,
        "errors":            errors,
        "warnings":          warnings,
        "broken_references": broken_refs,
    }
