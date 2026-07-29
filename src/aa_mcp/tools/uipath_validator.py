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
  9. Dependency versions use NuGet bracket notation; targetFramework / expressionLanguage recognized
 10. Every .xaml uses the modern VisualBasic.Settings="{x:Null}" + TextExpression imports (no legacy mva block)
 11. Every type argument uses a declared xmlns prefix, and x: type args are valid XAML intrinsics
     (catches e.g. x:Exception / x:DateTime, which must use a System-namespace prefix)

This is a STATIC check — it does not compile the project. For a real compile/load
gate, see compile_check_uipath_project (requires a Windows host + UiPath CLI).
Does not require UiPath Studio or any network access.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_NS_UI      = "http://schemas.uipath.com/workflow/activities"
_NS_XAML    = "http://schemas.microsoft.com/winfx/2006/xaml"
_INVOKE_TAG = f"{{{_NS_UI}}}InvokeWorkflowFile"
_X_CLASS    = f"{{{_NS_XAML}}}Class"

_REQUIRED_PROJECT_KEYS = ("name", "main", "schemaVersion", "dependencies")

# Recognized UiPath project.json schema versions. Studio's
# WorkflowDataUpgrade.GetLatestProjectData() reads schemaVersion to detect the
# project version; an unrecognized value fails to open with
# "Error detecting project version". Modern Studio (2020.10+) uses "4.0".
_KNOWN_SCHEMA_VERSIONS = ("3.2", "4.0", "4.1", "4.2")

# Closed sets per UiPath (unknown values warn rather than error).
_KNOWN_TARGET_FRAMEWORKS = ("Windows", "Legacy", "Portable", "CrossPlatform")
_KNOWN_EXPRESSION_LANGUAGES = ("VisualBasic", "CSharp")

# NuGet dependency version notation: exact "[x]" or range "[x, )" / "(x, y]".
_DEP_VERSION_RE = re.compile(r"^[\[(].+[\])]$")

# The closed set of type names in the XAML language namespace (x:) valid as type
# arguments. Anything else with an x: prefix (e.g. x:Exception, x:DateTime) is NOT
# a XAML intrinsic and must use a System-namespace prefix — Studio fails to
# resolve it on load.
_X_INTRINSICS = frozenset({
    "Object", "Boolean", "Byte", "Char", "Decimal", "Double", "Int16", "Int32",
    "Int64", "Single", "String", "TimeSpan", "Uri", "Array", "Type", "List",
    "Dictionary",
})

# Type references appear in x:TypeArguments="..." and Type="...Argument(...)".
_TYPE_ATTR_RE = re.compile(r'(?:x:TypeArguments|\bType)="([^"]*)"')
_PREFIXED_TYPE_RE = re.compile(r"(\w+):(\w+)")
_XMLNS_PREFIX_RE = re.compile(r"xmlns:(\w+)\s*=")


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

    # schemaVersion value — an unrecognized value makes Studio fail to open the
    # project with "Error detecting project version" (thrown in
    # WorkflowDataUpgrade.GetLatestProjectData). Presence is already covered above.
    schema_version = project.get("schemaVersion")
    if schema_version is not None and schema_version not in _KNOWN_SCHEMA_VERSIONS:
        major = str(schema_version).split(".")[0]
        if major.isdigit() and int(major) < 3:
            errors.append(
                f"project.json schemaVersion '{schema_version}' is not a valid UiPath "
                "schema version — Studio will fail to open with 'Error detecting "
                "project version'. Use '4.0'."
            )
        else:
            warnings.append(
                f"project.json schemaVersion '{schema_version}' is not a recognized "
                f"value {list(_KNOWN_SCHEMA_VERSIONS)}; verify it opens in your Studio version."
            )

    # Dependency versions must use NuGet bracket notation ("[x]" or "[x, )")
    for dep_name, spec in (project.get("dependencies") or {}).items():
        if not (isinstance(spec, str) and _DEP_VERSION_RE.match(spec.strip())):
            errors.append(
                f"project.json dependency '{dep_name}' has invalid version '{spec}'; "
                "use exact '[x.y.z]' or minimum '[x.y.z, )' bracket notation."
            )

    # Enum sanity (warn-only — closed sets, but tolerate variants we don't know)
    tf = project.get("targetFramework")
    if tf is not None and tf not in _KNOWN_TARGET_FRAMEWORKS:
        warnings.append(
            f"project.json targetFramework '{tf}' is not one of {list(_KNOWN_TARGET_FRAMEWORKS)}."
        )
    el = project.get("expressionLanguage")
    if el is not None and el not in _KNOWN_EXPRESSION_LANGUAGES:
        warnings.append(
            f"project.json expressionLanguage '{el}' is not one of {list(_KNOWN_EXPRESSION_LANGUAGES)}."
        )

    # Main XAML exists
    main = project.get("main", "")
    if main and not (directory / main).exists():
        errors.append(f"Main workflow file not found: {main}")
    elif main and not main.lower().endswith(".xaml"):
        warnings.append(f"project.json main '{main}' does not end in .xaml.")

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
            raw = xaml_path.read_text(encoding="utf-8")
            tree = ET.parse(xaml_path)
        except (ET.ParseError, OSError) as exc:
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

        # Checks 10–11: modern VB settings/imports + type-argument resolution
        _check_xaml_static(fname, raw, errors, warnings)

    return checked


def _check_xaml_static(
    fname: str,
    raw: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """String-level XAML checks: modern VB settings/imports + type-arg resolution."""
    # Check 10: modern imports; no legacy mva:VisualBasicSettings block
    if "mva:" in raw or "VisualBasicSettings" in raw:
        errors.append(
            f"{fname}: legacy mva:VisualBasicSettings block present — rejected by "
            'Studio 2020.10+ ("Cannot set unknown member ...ImportedNamespaces"). '
            'Use VisualBasic.Settings="{x:Null}" + TextExpression imports.'
        )
    else:
        if 'VisualBasic.Settings="{x:Null}"' not in raw:
            warnings.append(
                f'{fname}: missing VisualBasic.Settings="{{x:Null}}" on the root Activity.'
            )
        if "TextExpression.NamespacesForImplementation" not in raw:
            warnings.append(
                f"{fname}: missing TextExpression.NamespacesForImplementation imports."
            )

    # Check 11: every type-argument prefix is declared, and x: type args are intrinsics
    declared = set(_XMLNS_PREFIX_RE.findall(raw))
    reported: set[tuple[str, str]] = set()
    for expr in _TYPE_ATTR_RE.findall(raw):
        for prefix, tname in _PREFIXED_TYPE_RE.findall(expr):
            key = (prefix, tname)
            if key in reported:
                continue
            if prefix not in declared:
                reported.add(key)
                errors.append(
                    f"{fname}: type argument '{prefix}:{tname}' uses an undeclared "
                    f"namespace prefix '{prefix}:'."
                )
            elif prefix == "x" and tname not in _X_INTRINSICS:
                reported.add(key)
                errors.append(
                    f"{fname}: '{prefix}:{tname}' is not a valid XAML (x:) intrinsic type; "
                    f"Studio can't resolve it — use a System-namespace prefix (e.g. s:{tname})."
                )


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
