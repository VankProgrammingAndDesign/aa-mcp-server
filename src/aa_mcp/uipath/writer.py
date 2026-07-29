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
import re
import uuid
import zipfile
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
    *,
    reference_project: str | None = None,
    package_versions: dict[str, str] | None = None,
    version_constraint: str = "exact",
) -> dict[str, Any]:
    """
    Full pipeline: parse → summarize → generate XAML → write to disk.

    Parameters
    ----------
    zip_path:    Absolute path to the AA A360 export ZIP.
    bot_name:    Exact bot name as returned by load_bot_package.
    output_path: Directory to write the UiPath project into (created if absent).
    reference_project: Optional path to a real Studio project.json (a file, a
                 project folder, or a .zip). Its dependency versions,
                 studioVersion, and schemaVersion are mirrored so the output
                 matches the target Studio environment.
    package_versions: Optional explicit {package: version} pins — highest
                 precedence, overriding both reference_project and the defaults.
    version_constraint: 'exact' (emit ``[x]``, default) or 'minimum' (``[x, )``).

    Returns a generation report dict.
    """
    # 0. Validate / normalize inputs, then mirror a reference Studio project
    intake_warnings: list[str] = []
    if version_constraint not in ("exact", "minimum"):
        intake_warnings.append(
            f"Unknown version_constraint '{version_constraint}'; using 'exact' "
            "(valid values: 'exact', 'minimum')."
        )
        version_constraint = "exact"
    if package_versions:
        # Strip any NuGet constraint notation from overrides so they match the
        # (already-normalized) reference_project path and never double-wrap.
        package_versions = {
            k: _parse_version_constraint(str(v)) for k, v in package_versions.items()
        }
        package_versions = {k: v for k, v in package_versions.items() if v}
    ref_versions, ref_studio, ref_schema, ref_warnings = (
        _load_reference_project(reference_project)
        if reference_project else ({}, None, None, [])
    )

    # 1. Parse the package
    contents = await asyncio.to_thread(package_parser.extract_package, zip_path)

    # 2. Find the master bot
    master_bot = _get_bot(contents, bot_name)
    if "error" in master_bot:
        return master_bot

    all_bots = contents["bots"]

    # 3. Build process summary
    summary = await asyncio.to_thread(
        mapper.build_process_summary, master_bot, all_bots,
        version_overrides=package_versions, reference_versions=ref_versions,
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
                mapper.build_process_summary, sub_bot, all_bots,
                version_overrides=package_versions, reference_versions=ref_versions,
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

    # 6b. Aggregate packages across master + every sub-bot (union by name).
    # `nuget_packages` = all detected packages (documented in ARCHITECTURE.md);
    # `referenced_packages` = only those a generated (typed) activity actually uses,
    # which become the project.json dependencies. resolve_package_version is
    # deterministic per name (first wins). implied = detected − referenced.
    merged_pkgs: dict[str, str] = {}
    merged_ref: dict[str, str] = {}
    for s in all_summaries.values():
        for pkg in s.get("nuget_packages", []):
            merged_pkgs.setdefault(pkg["name"], pkg["version"])
        for pkg in s.get("referenced_packages", []):
            merged_ref.setdefault(pkg["name"], pkg["version"])
    summary["nuget_packages"] = [
        {"name": n, "version": v} for n, v in sorted(merged_pkgs.items())
    ]
    summary["referenced_packages"] = [
        {"name": n, "version": v} for n, v in sorted(merged_ref.items())
    ]
    implied_packages = [
        p for p in summary["nuget_packages"] if p["name"] not in merged_ref
    ]

    # 7. Build project.json
    project_json = _build_project_json(
        summary, main_filename, bot_name,
        version_constraint=version_constraint,
        studio_version=ref_studio,
        schema_version=ref_schema,
        package_versions=package_versions,
        reference_versions=ref_versions,
    )
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
    if implied_packages:
        review_notes.insert(0,
            "Packages the original bot uses but the generated steps only stub as "
            "placeholders — add them in Studio (Manage Packages) as you implement the "
            "[PARTIAL]/[TODO] steps: "
            + ", ".join(f"{p['name']} {p['version']}" for p in implied_packages)
        )

    # 10. Warnings — input validation, reference-load issues, unresolved package
    # versions, large bot
    warnings: list[str] = list(intake_warnings) + list(ref_warnings)
    seen_warn: set[str] = set(warnings)
    for s in all_summaries.values():
        for w in s.get("version_warnings", []):
            if w not in seen_warn:
                seen_warn.add(w)
                warnings.append(w)
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
        "suggested_packages": implied_packages,
        "warnings": warnings,
    }


# ── Version + reference-project resolution ──────────────────────────────────────

_VERSION_TOKEN = re.compile(r"[0-9][0-9A-Za-z.\-+]*")


def _parse_version_constraint(raw: str) -> str:
    """Strip NuGet constraint notation to a plain version.

    '[25.10.2]' -> '25.10.2', '[25.10.2, )' -> '25.10.2', '2.4.10' -> '2.4.10'.
    Returns '' when no version token is present.
    """
    m = _VERSION_TOKEN.search(raw or "")
    return m.group(0) if m else ""


def _format_dependency_version(version: str, version_constraint: str) -> str:
    """Wrap a plain version in NuGet constraint notation for project.json."""
    if version_constraint == "minimum":
        return f"[{version}, )"
    return f"[{version}]"  # 'exact' (default)


def _load_reference_project(
    reference_project: str,
) -> tuple[dict[str, str], str | None, str | None, list[str]]:
    """
    Read a real Studio project.json and extract its dependency versions,
    studioVersion, and schemaVersion so generated projects can mirror the target
    environment instead of the built-in defaults.

    ``reference_project`` may point at a project.json file, a project folder
    containing one, or a .zip with one anywhere inside.

    Returns ``(dep_versions, studio_version, schema_version, warnings)``. On any
    failure returns ``({}, None, None, [warning])`` rather than raising.
    """
    warnings: list[str] = []
    raw: str | None = None
    p = Path(reference_project)
    try:
        if p.is_dir():
            pj = p / "project.json"
            raw = pj.read_text(encoding="utf-8") if pj.exists() else None
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                names = [n for n in zf.namelist()
                         if n.rsplit("/", 1)[-1] == "project.json"]
                if names:
                    names.sort(key=lambda n: n.count("/"))  # shallowest wins
                    raw = zf.read(names[0]).decode("utf-8")
        elif p.exists():
            raw = p.read_text(encoding="utf-8")
        else:
            warnings.append(f"reference_project not found: {reference_project}")
            return {}, None, None, warnings
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append(
            f"Could not read reference_project '{reference_project}': {exc}"
        )
        return {}, None, None, warnings

    if raw is None:
        warnings.append(
            f"No project.json found in reference_project: {reference_project}"
        )
        return {}, None, None, warnings

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        warnings.append(f"reference_project project.json is not valid JSON: {exc}")
        return {}, None, None, warnings

    dep_versions = {
        name: _parse_version_constraint(str(spec))
        for name, spec in (data.get("dependencies") or {}).items()
    }
    dep_versions = {k: v for k, v in dep_versions.items() if v}
    return dep_versions, data.get("studioVersion"), data.get("schemaVersion"), warnings


# ── project.json builder ───────────────────────────────────────────────────────

def _build_project_json(
    summary: dict[str, Any],
    main_xaml_filename: str,
    bot_name: str,
    *,
    version_constraint: str = "exact",
    studio_version: str | None = None,
    schema_version: str | None = None,
    package_versions: dict[str, str] | None = None,
    reference_versions: dict[str, str] | None = None,
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

    # Dependencies = only packages a generated (typed) activity actually references
    # (versions already resolved by the mapper). The bot's other *implied* packages
    # are labelled placeholders in the XAML, so declaring them would force Studio to
    # restore packages the scaffold never uses (and break restore where those aren't
    # available) — they are documented in ARCHITECTURE.md instead.
    referenced = summary.get("referenced_packages") or summary.get("nuget_packages", [])
    dependencies = {
        pkg["name"]: _format_dependency_version(pkg["version"], version_constraint)
        for pkg in referenced
    }
    # Always include System.Activities (resolver-based so an override/reference wins)
    if "UiPath.System.Activities" not in dependencies:
        version, _ = mapper.resolve_package_version(
            "UiPath.System.Activities",
            overrides=package_versions,
            reference_versions=reference_versions,
        )
        dependencies["UiPath.System.Activities"] = _format_dependency_version(
            version, version_constraint
        )

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

    # Structure mirrors a real UiPath Studio 25.10.1 project.json so the output
    # opens without an upgrade/normalize prompt and restores the LTS-bundled
    # packages from Studio's local feed. schemaVersion is the schema of THIS file
    # (read by WorkflowDataUpgrade.GetLatestProjectData to detect the project
    # version); an unrecognized value (e.g. "1.0") throws NotSupportedException
    # "Error detecting project version" and the project won't open. 25.10 uses "4.0".
    return {
        "name": sanitize_filename(bot_name),
        "projectId": str(uuid.uuid4()),
        "description": description,
        "main": main_xaml_filename,
        "dependencies": dependencies,
        "webServices": [],
        "entitiesStores": [],
        "schemaVersion": schema_version or "4.0",
        "studioVersion": studio_version or "25.10.1.0",
        "projectVersion": "1.0.0",
        "runtimeOptions": {
            "autoDispose": False,
            "netFrameworkLazyLoading": False,
            "isPausable": True,
            "isAttended": False,
            "requiresUserInteraction": False,
            "supportsPersistence": False,
            "workflowSerialization": "NewtonsoftJson",
            "excludedLoggedData": ["Private:*", "*password*"],
            "executionType": "Workflow",
            "readyForPiP": False,
            "startsInPiP": False,
            "mustRestoreAllDependencies": True,
            "pipType": "ChildSession",
        },
        "designOptions": {
            "projectProfile": "Developement",  # UiPath's own spelling — keep for parity
            "outputType": "Process",
            "libraryOptions": {"privateWorkflows": []},
            "processOptions": {"ignoredFiles": []},
            "fileInfoCollection": [],
            "saveToCloud": False,
        },
        "expressionLanguage": "VisualBasic",
        "entryPoints": [
            {
                "filePath": main_xaml_filename,
                "uniqueId": str(uuid.uuid4()),
                "input": entry_inputs,
                "output": entry_outputs,
            }
        ],
        "isTemplate": False,
        "templateProjectData": {},
        "publishData": {},
        "targetFramework": "Windows",
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
