"""
Documentation generator for AA → UiPath migration.

Builds Markdown from structured ProcessSummary data — no AI required.

Entry points:
  generate_pdd(summary)                          → PDD.md content
  generate_architecture_doc(master_summary, ...) → ARCHITECTURE.md content
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from aa_mcp.uipath.mapper import sanitize_filename

# ── Constants ──────────────────────────────────────────────────────────────────

_FLOW_CAP     = 50   # max steps emitted in Process Flow section
_LOCAL_VAR_CAP = 30  # max local variables shown in Local Variables section


# ── Public entry points ────────────────────────────────────────────────────────

def generate_pdd(summary: dict[str, Any]) -> str:
    """
    Build PDD.md content from a ProcessSummary dict.

    Covers: business overview, trigger, inputs/outputs, process flow,
    sub-processes, external systems, exception handling, local variables,
    and migration notes.
    """
    sections = (
        _pdd_header(summary)
        + _pdd_overview(summary)
        + _pdd_trigger()
        + _pdd_inputs(summary)
        + _pdd_outputs(summary)
        + _pdd_process_flow(summary)
        + _pdd_subprocesses(summary)
        + _pdd_external_systems(summary)
        + _pdd_exception_handling(summary)
        + _pdd_local_variables(summary)
        + _pdd_migration_notes(summary)
    )
    return "\n".join(sections)


def generate_architecture_doc(
    master_summary: dict[str, Any],
    all_summaries: dict[str, dict[str, Any]],
    sub_bots_generated: list[str],
    sub_bots_stubbed: list[str],
) -> str:
    """
    Build ARCHITECTURE.md content.

    master_summary:     ProcessSummary for the root bot.
    all_summaries:      resolved_bot_name → ProcessSummary for every bot
                        visited (including master).
    sub_bots_generated: XAML filenames of sub-bots with full workflows.
    sub_bots_stubbed:   XAML filenames of stub sub-bots.
    """
    sections = (
        _arch_header(master_summary)
        + _arch_bot_tree(master_summary, all_summaries,
                         set(sub_bots_stubbed))
        + _arch_workflow_files(master_summary, all_summaries,
                               sub_bots_generated, sub_bots_stubbed)
        + _arch_arguments(master_summary)
        + _arch_nuget(master_summary)
    )
    return "\n".join(sections)


# ── PDD section builders ───────────────────────────────────────────────────────

def _pdd_header(summary: dict[str, Any]) -> list[str]:
    bot_name = summary.get("bot_name", "Unknown")
    folder   = summary.get("folder_path", "")
    today    = datetime.date.today().isoformat()
    return [
        f"# Process Definition Document — {bot_name}",
        "",
        "> Auto-generated from Automation Anywhere A360 export.",
        "> Complete `[DESCRIBE]` placeholders before finalising.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| **Bot name** | {bot_name} |",
        f"| **Folder** | {folder or '—'} |",
        f"| **Generated** | {today} |",
        "| **Source** | Automation Anywhere A360 |",
        "| **Target** | UiPath Studio 25.10 |",
        "",
        "---",
        "",
    ]


def _pdd_overview(summary: dict[str, Any]) -> list[str]:
    bot_name    = summary.get("bot_name", "Unknown")
    ext_systems = summary.get("external_systems", [])
    stats       = summary.get("stats", {})
    total       = stats.get("total_steps", 0)
    active      = stats.get("active_steps", 0)
    cov         = stats.get("coverage_pct", 0.0)
    systems_str = ", ".join(ext_systems) if ext_systems else "none identified"
    return [
        "## 1. Business Process Overview",
        "",
        (
            f"**{_humanize(bot_name)}** is an automated process converted from "
            f"Automation Anywhere A360 to UiPath. It contains {total} steps "
            f"({active} active) and integrates with: {systems_str}. "
            f"Activity mapping coverage is {cov}%."
        ),
        "",
        "> **[DESCRIBE]** Explain the business purpose, who initiates the process, "
        "and the expected outcomes.",
        "",
    ]


def _pdd_trigger() -> list[str]:
    return [
        "## 2. Trigger and Schedule",
        "",
        "| Field | Value |",
        "|---|---|",
        "| **Trigger type** | [DESCRIBE: Manual / Scheduled / Event-driven] |",
        "| **Schedule** | [DESCRIBE: Cron expression or plain-English frequency] |",
        "| **Initiator** | [DESCRIBE: System or user role that starts the process] |",
        "",
    ]


def _pdd_inputs(summary: dict[str, Any]) -> list[str]:
    inputs = [v for v in summary.get("variables", []) if v.get("uipath_direction") == "In"]
    lines  = ["## 3. Process Inputs", ""]
    if not inputs:
        return lines + ["> No input arguments defined.", ""]
    lines += _md_table(
        ["Name", "Type (UiPath)", "AA Type", "Required", "Description"],
        [
            [v["name"], v["uipath_type"], v["aa_type"],
             "Yes" if v.get("input_required") else "No",
             v.get("description") or "—"]
            for v in inputs
        ],
    )
    return lines + [""]


def _pdd_outputs(summary: dict[str, Any]) -> list[str]:
    outputs = [v for v in summary.get("variables", []) if v.get("uipath_direction") == "Out"]
    lines   = ["## 4. Process Outputs", ""]
    if not outputs:
        return lines + ["> No output arguments defined.", ""]
    lines += _md_table(
        ["Name", "Type (UiPath)", "AA Type", "Description"],
        [
            [v["name"], v["uipath_type"], v["aa_type"], v.get("description") or "—"]
            for v in outputs
        ],
    )
    return lines + [""]


def _pdd_process_flow(summary: dict[str, Any]) -> list[str]:
    """
    Group active steps into phases using Step/Comment nodes at depth 0-1.
    Non-Step leaf children are listed under their parent phase.
    Falls back to a flat list when no phases are present.
    Capped at _FLOW_CAP emitted entries.
    """
    active = [s for s in summary.get("steps", []) if not s.get("disabled")]
    lines  = ["## 5. Process Flow", ""]

    if not active:
        return lines + ["> No active steps found.", ""]

    _PHASE_PKGS = {"step", "comment"}
    emitted = 0
    i, n    = 0, len(active)

    while i < n and emitted < _FLOW_CAP:
        step = active[i]
        pkg  = step.get("aa_package", "").lower()
        dep  = step.get("depth", 0)

        if pkg in _PHASE_PKGS and dep <= 1:
            lines.append(f"### {step['label'] or step['aa_command'] or 'Phase'}")
            lines.append("")
            emitted += 1
            i += 1
            while i < n and emitted < _FLOW_CAP:
                child     = active[i]
                child_dep = child.get("depth", 0)
                child_pkg = child.get("aa_package", "").lower()
                if child_dep <= dep:
                    break
                if child_dep == dep + 1 and child_pkg not in _PHASE_PKGS:
                    lines.append(_flow_bullet(child))
                    emitted += 1
                i += 1
            lines.append("")
        else:
            lines.append(_flow_bullet(step))
            emitted += 1
            i += 1

    remaining = n - i
    if remaining > 0:
        lines.append(
            f"\n> _{remaining} additional steps not shown — see XAML for full detail._"
        )
    lines.append("")
    return lines


def _flow_bullet(step: dict[str, Any]) -> str:
    status   = step.get("mapping_status", "")
    badge    = " `[PARTIAL]`" if status == "partial" else " `[TODO]`" if status == "todo" else ""
    label    = step.get("label") or step.get("aa_command", "")
    activity = step.get("uipath_activity", "")
    return f"- **{label}**{badge} → `{activity}`"


def _pdd_subprocesses(summary: dict[str, Any]) -> list[str]:
    sub_bots = summary.get("sub_bots_called", [])
    lines    = ["## 6. Sub-Processes", ""]
    if not sub_bots:
        return lines + ["> No sub-bots called.", ""]
    lines += _md_table(
        ["Name", "In Package", "XAML File", "Subtask Path"],
        [
            [
                sub.get("resolved_bot_name") or "— (unresolved)",
                "Yes" if sub.get("resolved_bot_name") else "No (stub)",
                sub.get("xaml_filename", "—"),
                sub.get("subtask_path", "—"),
            ]
            for sub in sub_bots
        ],
    )
    return lines + [""]


def _pdd_external_systems(summary: dict[str, Any]) -> list[str]:
    systems = summary.get("external_systems", [])
    lines   = ["## 7. External Systems", ""]
    if not systems:
        return lines + ["> No external systems detected.", ""]
    lines += _md_table(
        ["System", "Integration Type", "Notes"],
        [[s, "[DESCRIBE: API / DB / File / UI]", "[DESCRIBE: credentials, endpoints]"]
         for s in systems],
    )
    return lines + [""]


def _pdd_exception_handling(summary: dict[str, Any]) -> list[str]:
    eh       = summary.get("error_handling", {})
    detected = eh.get("detected", False)
    pattern  = eh.get("pattern", "None detected")
    lines    = [
        "## 8. Exception Handling",
        "",
        f"**Detected:** {'Yes' if detected else 'No'}  ",
        f"**Pattern:** {pattern}",
        "",
    ]
    if detected:
        lines += [
            "A `TryCatch` block was found in the source AA bot and has been "
            "mapped to a UiPath `TryCatch` activity. Review the "
            "`[TODO] Handle Exception` Sequence in Studio and implement "
            "catch-branch logic.",
            "",
        ]
    else:
        lines += [
            "> **[DESCRIBE]** No error handler was detected in the source bot. "
            "Define the exception strategy for the UiPath implementation.",
            "",
        ]
    return lines


def _pdd_local_variables(summary: dict[str, Any]) -> list[str]:
    locals_ = [v for v in summary.get("variables", []) if v.get("uipath_direction") is None]
    lines   = ["## 9. Local Variables", ""]
    if not locals_:
        return lines + ["> No local variables defined.", ""]
    capped = locals_[:_LOCAL_VAR_CAP]
    lines += _md_table(
        ["Name", "AA Type", "UiPath Type", "Default", "Description"],
        [
            [v["name"], v["aa_type"], v["uipath_type"],
             _format_default(v.get("default_value")), v.get("description") or "—"]
            for v in capped
        ],
    )
    if len(locals_) > _LOCAL_VAR_CAP:
        lines.append(f"\n> _Showing {_LOCAL_VAR_CAP} of {len(locals_)} local variables._")
    return lines + [""]


def _pdd_migration_notes(summary: dict[str, Any]) -> list[str]:
    stats = summary.get("stats", {})
    lines = ["## 10. Migration Notes", ""]
    lines += _md_table(
        ["Metric", "Value"],
        [
            ["Mapping coverage",              f"{stats.get('coverage_pct', 0.0)}%"],
            ["Mapped steps",                  str(stats.get("mapped_count", 0))],
            ["Partial steps `[PARTIAL]`",     str(stats.get("partial_count", 0))],
            ["Unresolved steps `[TODO]`",     str(stats.get("todo_count", 0))],
            ["Disabled steps",                str(stats.get("disabled_step_count", 0))],
            ["UI Automation steps",           str(stats.get("ui_automation_step_count", 0))],
            ["Total steps",                   str(stats.get("total_steps", 0))],
        ],
    )
    lines += [
        "",
        "### Action Required",
        "",
        "1. In Studio, search for `[PARTIAL]` — fill in parameters "
        "(expressions, file paths, connection strings).",
        "2. Search for `[TODO]` — implement manually or remove if obsolete.",
    ]
    ui_count = stats.get("ui_automation_step_count", 0)
    if ui_count:
        lines.append(
            f"3. **{ui_count} UI Automation step(s)** require manual selector "
            "work in UiPath Studio's UI Explorer."
        )
    return lines + [""]


# ── Architecture doc builders ──────────────────────────────────────────────────

def _arch_header(master_summary: dict[str, Any]) -> list[str]:
    bot_name = master_summary.get("bot_name", "Unknown")
    today    = datetime.date.today().isoformat()
    return [
        f"# Architecture Overview — {bot_name}",
        "",
        f"Generated: {today}  ",
        "Source: Automation Anywhere A360  ",
        "Target: UiPath Studio 25.10",
        "",
        "---",
        "",
    ]


def _arch_bot_tree(
    master_summary: dict[str, Any],
    all_summaries: dict[str, dict[str, Any]],
    stubbed_xaml: set[str],
) -> list[str]:
    """
    Render a text-art bot hierarchy tree.

    Recurses via sub_bots_called on each summary in all_summaries.
    visited set prevents infinite loops on circular references.
    """
    lines: list[str] = ["## 1. Bot Hierarchy", "", "```"]

    def _node(name: str, prefix: str, is_last: bool, visited: set[str]) -> None:
        connector  = "└── " if is_last else "├── "
        xaml_name  = sanitize_filename(name) + ".xaml"
        is_master  = name == master_summary.get("bot_name")
        is_stub    = xaml_name in stubbed_xaml
        annotation = " (master)" if is_master else " [stub]" if is_stub else ""
        lines.append(f"{prefix}{connector}{name}{annotation}")

        if name in visited or name not in all_summaries:
            return
        visited.add(name)

        children   = all_summaries[name].get("sub_bots_called", [])
        child_pfx  = prefix + ("    " if is_last else "│   ")
        for idx, child in enumerate(children):
            child_name = (
                child.get("resolved_bot_name")
                or child.get("subtask_path", "").rstrip("/").split("/")[-1]
            )
            _node(child_name, child_pfx, idx == len(children) - 1, visited)

    master_name = master_summary.get("bot_name", "Master")
    _node(master_name, "", True, set())
    return lines + ["```", ""]


def _arch_workflow_files(
    master_summary: dict[str, Any],
    all_summaries: dict[str, dict[str, Any]],
    sub_bots_generated: list[str],
    sub_bots_stubbed: list[str],
) -> list[str]:
    # Build a reverse index: sanitized_name → original key in all_summaries
    reverse: dict[str, str] = {sanitize_filename(k): k for k in all_summaries}

    lines = ["## 2. Workflow Files", ""]
    rows: list[list[str]] = []

    master_name  = master_summary.get("bot_name", "")
    master_stats = master_summary.get("stats", {})
    rows.append([
        sanitize_filename(master_name) + ".xaml",
        "Master workflow",
        str(master_stats.get("total_steps", 0)),
        f"{master_stats.get('coverage_pct', 0.0)}%",
    ])

    for xaml_file in sorted(sub_bots_generated):
        stem    = xaml_file.removesuffix(".xaml")
        key     = reverse.get(stem, stem)
        s       = all_summaries.get(key, {})
        st      = s.get("stats", {})
        rows.append([
            xaml_file, "Sub-workflow",
            str(st.get("total_steps", 0)),
            f"{st.get('coverage_pct', 0.0)}%",
        ])

    for xaml_file in sorted(sub_bots_stubbed):
        rows.append([xaml_file, "Sub-workflow (stub)", "—", "—"])

    lines += _md_table(["File", "Role", "Steps", "Coverage"], rows)
    return lines + [""]


def _arch_arguments(master_summary: dict[str, Any]) -> list[str]:
    variables = master_summary.get("variables", [])
    inputs    = [v for v in variables if v.get("uipath_direction") == "In"]
    outputs   = [v for v in variables if v.get("uipath_direction") == "Out"]
    lines     = ["## 3. Master Workflow Arguments", ""]

    if inputs:
        lines += ["### Inputs", ""]
        lines += _md_table(
            ["Name", "Type", "Required", "Description"],
            [[v["name"], v["uipath_type"],
              "Yes" if v.get("input_required") else "No",
              v.get("description") or "—"]
             for v in inputs],
        )
        lines.append("")

    if outputs:
        lines += ["### Outputs", ""]
        lines += _md_table(
            ["Name", "Type", "Description"],
            [[v["name"], v["uipath_type"], v.get("description") or "—"]
             for v in outputs],
        )
        lines.append("")

    if not inputs and not outputs:
        lines += ["> No arguments on the master workflow — uses local variables only.", ""]

    return lines


def _arch_nuget(master_summary: dict[str, Any]) -> list[str]:
    nuget = master_summary.get("nuget_packages", [])
    referenced = {p["name"] for p in master_summary.get("referenced_packages", [])}
    lines = ["## 4. NuGet Dependencies", ""]
    if not nuget:
        return lines + ["> No NuGet packages recorded.", ""]
    rows = [
        [p["name"], p["version"],
         "Declared" if p["name"] in referenced else "Add when implementing"]
        for p in nuget
    ]
    lines += _md_table(["Package", "Version", "In project.json"], rows)
    return lines + [
        "",
        "> Only **Declared** packages are in `project.json` — the ones a generated "
        "activity actually references. The rest are implied by the original bot; add "
        "them in Studio as you replace the `[PARTIAL]`/`[TODO]` placeholders.",
        "",
    ]


# ── Shared utilities ───────────────────────────────────────────────────────────

def _format_default(value: Any) -> str:
    """Return a display-safe default value string for a variable."""
    if value is None or value == "":
        return ""
    if isinstance(value, (bool, int, float)):
        return str(value)
    if isinstance(value, str):
        return value[:80] + ("…" if len(value) > 80 else "")
    # Complex types (dict/list from AA) — show the type tag if present
    if isinstance(value, dict):
        vtype = value.get("type", "")
        if vtype:
            return f"[{vtype}]"
    return "[complex]"


def _humanize(name: str) -> str:
    """Convert snake_case / CamelCase identifiers to readable title-cased words."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return spaced.strip().title()


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Render a GitHub-flavoured Markdown table."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(" --- " for _ in headers) + "|",
    ]
    for row in rows:
        cells = [str(c).replace("|", "\\|") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines
