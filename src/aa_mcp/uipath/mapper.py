"""
Mapping layer: Automation Anywhere commands → UiPath activities.

Provides:
- ACTIVITY_MAP: lookup table keyed on (package, command) tuples
- build_process_summary(): analyse a parsed AA bot and return a structured summary
- lookup_mapping(): resolve the best ActivityMapping for a package/command pair
- sanitize_filename(): convert bot names to safe filesystem stems
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── Status constants ───────────────────────────────────────────────────────────

MAPPED = "mapped"    # Full WF4 activity generated
PARTIAL = "partial"  # Named placeholder; human fills parameters in Studio
TODO = "todo"        # No meaningful mapping; empty Sequence with explanation


# ── ActivityMapping ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ActivityMapping:
    status: str               # MAPPED | PARTIAL | TODO
    uipath_activity: str      # e.g. "InvokeWorkflowFile", "Sequence"
    uipath_package: str | None  # NuGet package name; None = core WF4 (no extra dependency)
    notes: str                # Shown in [PARTIAL]/[TODO] DisplayName


# ── Mapping table ──────────────────────────────────────────────────────────────
# Keyed on (package.lower(), command.lower()).
# Use ("package", "*") as a wildcard for all commands in that package.
# Lookup order: exact match → wildcard → default TODO.

ACTIVITY_MAP: dict[tuple[str, str], ActivityMapping] = {

    # ── Control flow ──────────────────────────────────────────────────────────
    ("taskbot", "runtask"):              ActivityMapping(MAPPED,   "InvokeWorkflowFile",        None,                                    "Subtask path becomes .xaml file reference"),
    ("taskbot", "stoptask"):             ActivityMapping(MAPPED,   "Throw",                     None,                                    "Raises exception to stop execution"),
    ("loop",    "loop.commands.start"):  ActivityMapping(MAPPED,   "ForEach",                   None,                                    "Needs loop variable binding"),
    ("loop",    "loop.commands.break"):  ActivityMapping(MAPPED,   "Break",                     None,                                    "Loop break"),
    ("loop",    "iterate"):              ActivityMapping(MAPPED,   "ForEach",                   None,                                    "Iterate collection"),
    ("loop",    "while"):                ActivityMapping(PARTIAL,  "While",                     None,                                    "Condition expression needs manual mapping"),
    ("loop",    "*"):                    ActivityMapping(MAPPED,   "ForEach",                   None,                                    "Needs loop variable binding"),
    ("if",      "if"):                   ActivityMapping(PARTIAL,  "If",                        None,                                    "Condition expression needs manual mapping"),
    ("if",      "*"):                    ActivityMapping(PARTIAL,  "If",                        None,                                    "Condition expression needs manual mapping"),
    ("errorhandler", "try"):             ActivityMapping(MAPPED,   "TryCatch",                  None,                                    "Wraps children; catch branch maps to Catches"),
    ("errorhandler", "*"):               ActivityMapping(MAPPED,   "TryCatch",                  None,                                    "Error handling wrapper"),
    ("step",    "step"):                 ActivityMapping(MAPPED,   "Sequence",                  None,                                    "Groups child actions"),
    ("step",    "*"):                    ActivityMapping(MAPPED,   "Sequence",                  None,                                    "Groups child actions"),
    ("comment", "comment"):              ActivityMapping(MAPPED,   "Sequence",                  None,                                    "Comment / annotation"),
    ("comment", "*"):                    ActivityMapping(MAPPED,   "Sequence",                  None,                                    "Comment / annotation"),

    # ── String / Number / Variable ────────────────────────────────────────────
    ("string",   "*"):                   ActivityMapping(PARTIAL,  "Assign",                    None,                                    "Expression needs manual mapping"),
    ("number",   "*"):                   ActivityMapping(PARTIAL,  "Assign",                    None,                                    "Expression needs manual mapping"),
    ("variable", "assign"):              ActivityMapping(PARTIAL,  "Assign",                    None,                                    "Value expression needs manual mapping"),
    ("variable", "*"):                   ActivityMapping(PARTIAL,  "Assign",                    None,                                    "Expression needs manual mapping"),
    ("boolean",  "*"):                   ActivityMapping(PARTIAL,  "Assign",                    None,                                    "Boolean expression needs manual mapping"),

    # ── Datetime ──────────────────────────────────────────────────────────────
    ("datetime", "*"):                   ActivityMapping(PARTIAL,  "Assign",                    None,                                    "DateTime expression needs manual mapping"),

    # ── File ──────────────────────────────────────────────────────────────────
    ("file",  "readfrom"):               ActivityMapping(PARTIAL,  "ReadTextFile",              "UiPath.System.Activities",              "File path needs mapping"),
    ("file",  "writeto"):                ActivityMapping(PARTIAL,  "WriteTextFile",             "UiPath.System.Activities",              "File path and content need mapping"),
    ("file",  "copyfiles"):              ActivityMapping(PARTIAL,  "CopyFile",                  "UiPath.System.Activities",              "Source/destination paths needed"),
    ("file",  "deletefiles"):            ActivityMapping(PARTIAL,  "DeleteFile",                "UiPath.System.Activities",              "File path needed"),
    ("file",  "renamefiles"):            ActivityMapping(PARTIAL,  "MoveFile",                  "UiPath.System.Activities",              "Source/destination paths needed"),
    ("file",  "fileexists"):             ActivityMapping(PARTIAL,  "PathExists",                "UiPath.System.Activities",              "Path needed"),
    ("file",  "*"):                      ActivityMapping(PARTIAL,  "Sequence",                  "UiPath.System.Activities",              "Map to appropriate file activity"),

    # ── Folder ────────────────────────────────────────────────────────────────
    ("folder", "createfolder"):          ActivityMapping(PARTIAL,  "CreateDirectory",           "UiPath.System.Activities",              "Path needed"),
    ("folder", "deletefolder"):          ActivityMapping(PARTIAL,  "DeleteDirectory",           "UiPath.System.Activities",              "Path needed"),
    ("folder", "zipfiles"):              ActivityMapping(PARTIAL,  "ZipFiles",                  "UiPath.System.Activities",              "Source/destination paths needed"),
    ("folder", "*"):                     ActivityMapping(PARTIAL,  "Sequence",                  "UiPath.System.Activities",              "Map to appropriate folder activity"),

    # ── Email ─────────────────────────────────────────────────────────────────
    ("email",  "sendmailv2"):            ActivityMapping(PARTIAL,  "Send SMTP Mail Message",    "UiPath.Mail.Activities",                "SMTP server/credentials needed"),
    ("email",  "sendmail"):              ActivityMapping(PARTIAL,  "Send SMTP Mail Message",    "UiPath.Mail.Activities",                "SMTP server/credentials needed"),
    ("email",  "*"):                     ActivityMapping(PARTIAL,  "Sequence",                  "UiPath.Mail.Activities",                "Map to mail activity"),

    # ── Excel ─────────────────────────────────────────────────────────────────
    ("excel_ms", "openspreadsheet"):     ActivityMapping(PARTIAL,  "Excel Application Scope",   "UiPath.Excel.Activities",               "File path needed"),
    ("excel_ms", "closespreadsheet"):    ActivityMapping(PARTIAL,  "Sequence",                  "UiPath.Excel.Activities",               "Handled by surrounding Excel scope"),
    ("excel_ms", "readfrom"):            ActivityMapping(PARTIAL,  "Read Range",                "UiPath.Excel.Activities",               "Sheet/range needed"),
    ("excel_ms", "writeto"):             ActivityMapping(PARTIAL,  "Write Range",               "UiPath.Excel.Activities",               "Sheet/range/data needed"),
    ("excel_ms", "setcell"):             ActivityMapping(PARTIAL,  "Write Cell",                "UiPath.Excel.Activities",               "Cell address needed"),
    ("excel_ms", "gotocell"):            ActivityMapping(PARTIAL,  "Go To Cell",                "UiPath.Excel.Activities",               "Cell address needed"),
    ("excel_ms", "*"):                   ActivityMapping(PARTIAL,  "Sequence",                  "UiPath.Excel.Activities",               "Map to Excel activity"),

    # ── Database ──────────────────────────────────────────────────────────────
    ("database", "connect"):             ActivityMapping(PARTIAL,  "Connect",                   "UiPath.Database.Activities",            "Connection string/driver needed"),
    ("database", "disconnect"):          ActivityMapping(PARTIAL,  "Disconnect",                "UiPath.Database.Activities",            "Connection variable needed"),
    ("database", "select"):              ActivityMapping(PARTIAL,  "ExecuteQuery",              "UiPath.Database.Activities",            "SQL and connection needed"),
    ("database", "sqlquery"):            ActivityMapping(PARTIAL,  "ExecuteQuery",              "UiPath.Database.Activities",            "SQL and connection needed"),
    ("database", "insertupdate"):        ActivityMapping(PARTIAL,  "ExecuteNonQuery",           "UiPath.Database.Activities",            "SQL and connection needed"),
    ("database", "insert"):              ActivityMapping(PARTIAL,  "ExecuteNonQuery",           "UiPath.Database.Activities",            "SQL and connection needed"),
    ("database", "*"):                   ActivityMapping(PARTIAL,  "Sequence",                  "UiPath.Database.Activities",            "Map to database activity"),

    # ── REST / HTTP ───────────────────────────────────────────────────────────
    ("rest", "*"):                       ActivityMapping(PARTIAL,  "HTTP Request",              "UiPath.WebAPI.Activities",              "URL/headers needed"),

    # ── Logging ───────────────────────────────────────────────────────────────
    ("logtofile", "*"):                  ActivityMapping(PARTIAL,  "Log Message",               None,                                    "Log level and message needed"),

    # ── Credentials ───────────────────────────────────────────────────────────
    ("credential",              "*"):    ActivityMapping(PARTIAL,  "Get Secure Credential",     "UiPath.Credentials.Activities",         "Asset name needed"),
    ("a360credentialutilities", "*"):    ActivityMapping(PARTIAL,  "Get Secure Credential",     "UiPath.Credentials.Activities",         "Asset name needed"),

    # ── MessageBox ────────────────────────────────────────────────────────────
    ("messagebox", "*"):                 ActivityMapping(PARTIAL,  "Message Box",               "UiPath.System.Activities",              "Message text needed"),

    # ── System ────────────────────────────────────────────────────────────────
    ("system", "*"):                     ActivityMapping(PARTIAL,  "Assign",                    None,                                    "Map to appropriate System activity"),

    # ── Delay / Wait ─────────────────────────────────────────────────────────
    ("delay", "*"):                      ActivityMapping(PARTIAL,  "Delay",                     None,                                    "Duration needs mapping"),
    ("wait",  "*"):                      ActivityMapping(TODO,     "Sequence",                  None,                                    "Map to Wait For Element or Delay"),

    # ── UI Automation — all TODO ──────────────────────────────────────────────
    ("recorder",         "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "Manual selector work required"),
    ("browser",          "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "Manual selector work required"),
    ("keystrokes",       "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "Map to Type Into or Send Hotkey"),
    ("mouse",            "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "Map to Click activity"),
    ("window",           "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "Map to Find Window or Attach Window"),
    ("screen",           "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "Map to Screenshot or Find Element"),
    ("imagerecognition", "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "Image-based UI automation"),
    ("ocr",              "*"):           ActivityMapping(TODO,     "Sequence",                  "UiPath.UIAutomation.Activities",        "OCR activity needs engine config"),

    # ── SharePoint ────────────────────────────────────────────────────────────
    ("sharepoint", "*"):                 ActivityMapping(TODO,     "Sequence",                  "UiPath.MicrosoftOffice365.Activities",  "Manual O365 config required"),

    # ── Scripting ─────────────────────────────────────────────────────────────
    ("vbscript", "*"):                   ActivityMapping(TODO,     "InvokeCode",                None,                                    "Migrate VBScript logic manually"),
    ("python",   "*"):                   ActivityMapping(TODO,     "InvokeCode",                "UiPath.Python.Activities",              "Migrate Python script manually"),

    # ── Analytics (AA BotInsight) ─────────────────────────────────────────────
    ("analyze",  "*"):                   ActivityMapping(TODO,     "Sequence",                  None,                                    "No UiPath BotInsight equivalent — remove or replace with custom logging"),
}


# ── Variable type mapping ──────────────────────────────────────────────────────

AA_TYPE_TO_UIPATH: dict[str, str] = {
    "STRING":     "x:String",
    "NUMBER":     "x:Double",
    "BOOLEAN":    "x:Boolean",
    "LIST":       "scg:List(x:Object)",
    "DICTIONARY": "scg:Dictionary(x:String,x:Object)",
    "DATE":       "s:DateTime",
    "DATETIME":   "s:DateTime",
    "TABLE":      "sd:DataTable",
    "CREDENTIAL": "x:String",
    "FILE":       "x:String",
    "BLOB":       "x:Object",
}

_DEFAULT_UIPATH_TYPE = "x:Object"


# ── NuGet version pins ─────────────────────────────────────────────────────────

# ── External system labels (for process summary) ──────────────────────────────

_SYSTEM_MAP: dict[str, str] = {
    "database":                "Database",
    "email":                   "Email/SMTP",
    "excel_ms":                "Excel",
    "sharepoint":              "SharePoint/Office365",
    "rest":                    "REST API",
    "recorder":                "UI Automation",
    "browser":                 "UI Automation",
    "keystrokes":              "UI Automation",
    "mouse":                   "UI Automation",
    "screen":                  "UI Automation",
    "window":                  "UI Automation",
    "imagerecognition":        "UI Automation",
    "ocr":                     "UI Automation",
    "credential":              "Credential Vault",
    "a360credentialutilities": "Credential Vault",
    "logtofile":               "File Logging",
}


# ── NuGet version pins ─────────────────────────────────────────────────────────

# Version pins aligned to a real UiPath Studio 25.10.1 (LTS) environment.
# The five packages a blank 25.10.1 project ships with are pinned to the exact
# LTS versions bundled in Studio's local Packages folder, so they restore
# offline with no feed access; the rest are the latest stable on the Official
# feed. Sources of truth: a blank 25.10.1 project.json + the Official feed index.
NUGET_VERSIONS: dict[str, str] = {
    "UiPath.System.Activities":             "25.10.2",   # LTS-bundled (local)
    "UiPath.UIAutomation.Activities":       "25.10.16",  # LTS-bundled (local)
    "UiPath.Excel.Activities":              "3.2.1",     # LTS-bundled (local)
    "UiPath.Mail.Activities":               "2.4.10",    # LTS-bundled (local)
    "UiPath.Testing.Activities":            "25.10.0",   # LTS-bundled (local)
    "UiPath.WebAPI.Activities":             "2.5.2",     # latest stable (feed)
    "UiPath.Database.Activities":           "2.1.1",     # latest stable (feed)
    "UiPath.Credentials.Activities":        "3.1.1",     # latest stable (feed)
    "UiPath.MicrosoftOffice365.Activities": "3.10.10",   # latest stable (feed)
    "UiPath.Python.Activities":             "2.2.1",     # latest stable (feed)
}


def resolve_package_version(
    pkg_name: str,
    *,
    overrides: dict[str, str] | None = None,
    reference_versions: dict[str, str] | None = None,
) -> tuple[str, bool]:
    """
    Resolve the pinned version for a NuGet package.

    Precedence (highest first): explicit ``overrides`` -> ``reference_versions``
    (mirrored from a real Studio project) -> the built-in NUGET_VERSIONS table.

    Returns ``(version, is_fallback)``. ``is_fallback`` is True ONLY when the
    package is unknown to every source and the placeholder ``"1.0.0"`` is used,
    so callers can surface it instead of silently shipping a bogus pin.
    """
    if overrides and pkg_name in overrides:
        return overrides[pkg_name], False
    if reference_versions and pkg_name in reference_versions:
        return reference_versions[pkg_name], False
    if pkg_name in NUGET_VERSIONS:
        return NUGET_VERSIONS[pkg_name], False
    return "1.0.0", True


# ── Public helpers ─────────────────────────────────────────────────────────────

def lookup_mapping(package: str, command: str) -> ActivityMapping:
    """Return the best ActivityMapping for an AA package/command pair."""
    pkg = package.lower()
    cmd = command.lower()
    if (pkg, cmd) in ACTIVITY_MAP:
        return ACTIVITY_MAP[(pkg, cmd)]
    if (pkg, "*") in ACTIVITY_MAP:
        return ACTIVITY_MAP[(pkg, "*")]
    return ActivityMapping(
        TODO, "Sequence", None,
        f"No mapping found for {package}.{command} — implement manually",
    )


def sanitize_filename(name: str) -> str:
    """Convert a bot name to a safe filesystem/XML class name stem.

    & is replaced with 'And' for readability (e.g. T&M → TAndM).
    All other non-word characters become underscores.
    """
    safe = name.replace("&", "And")
    safe = re.sub(r"[^\w\-]", "_", safe)
    safe = re.sub(r"_+", "_", safe)
    return safe.strip("_") or "Bot"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _map_variable(var: dict[str, Any]) -> dict[str, Any]:
    aa_type = (var.get("type") or "STRING").upper()
    uipath_type = AA_TYPE_TO_UIPATH.get(aa_type, _DEFAULT_UIPATH_TYPE)
    scope = var.get("scope", "local")
    direction_map = {"input": "In", "output": "Out", "workItem": "InOut"}
    return {
        "name": var.get("name", ""),
        "aa_type": aa_type,
        "uipath_type": uipath_type,
        "scope": scope,
        "uipath_direction": direction_map.get(scope),  # None for "local"
        "default_value": var.get("default_value"),
        "description": var.get("description", ""),
        "input_required": var.get("input_required", False),
    }


_ASSIGN_COMMANDS = frozenset({
    "assign", "concatenate", "substring", "split", "trim",
    "toupper", "tolower", "contains", "replace", "tostring", "add",
    "subtract", "multiply", "divide", "increment", "decrement",
})


def _map_action(action: dict[str, Any]) -> dict[str, Any]:
    pkg = action.get("package", "")
    cmd = action.get("command", "")
    mapping = lookup_mapping(pkg, cmd)
    output_vars = action.get("output_variables", [])
    raw_label = action.get("label", "") or cmd or pkg

    # Improve labels for common patterns
    if pkg == "TaskBot" and cmd == "runTask":
        path = action.get("subtask_path", "")
        sub_name = path.rstrip("/").split("/")[-1] if path else raw_label
        label = f"Run {sub_name}"
    elif cmd.lower() in _ASSIGN_COMMANDS and output_vars:
        target = output_vars[0]
        label = f"Assign \u2192 {target}"  # → arrow
    else:
        label = raw_label

    return {
        "index": action.get("index", 0),
        "depth": action.get("depth", 0),
        "label": label,
        "aa_package": pkg,
        "aa_command": cmd,
        "disabled": action.get("disabled", False),
        "subtask_path": action.get("subtask_path", ""),
        "output_variables": action.get("output_variables", []),
        "uipath_activity": mapping.uipath_activity,
        "uipath_package": mapping.uipath_package,
        "mapping_status": mapping.status,
        "mapping_notes": mapping.notes,
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def build_process_summary(
    bot: dict[str, Any],
    all_bots: dict[str, Any],
    *,
    version_overrides: dict[str, str] | None = None,
    reference_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build a structured ProcessSummary from a parsed AA bot dict.

    bot:      Bot dict from package_parser (has name, actions, variables, _raw).
    all_bots: All bots from the same package, used to resolve sub-bot names.

    Returns a dict with keys: bot_name, folder_path, overview, variables,
    steps, sub_bots_called, error_handling, external_systems, nuget_packages, stats.
    """
    bot_name = bot.get("name", "")
    folder_path = bot.get("folder_path", "")

    # Map variables
    mapped_vars = [_map_variable(v) for v in bot.get("variables", [])]

    # Deduplicate variable names (rare but possible across scopes)
    seen_var_names: dict[str, int] = {}
    for v in mapped_vars:
        n = v["name"]
        if n in seen_var_names:
            seen_var_names[n] += 1
            v["name"] = f"{n}_{seen_var_names[n]}"
        else:
            seen_var_names[n] = 0

    # Map actions
    actions = bot.get("actions", [])
    mapped_steps = [_map_action(a) for a in actions]

    # Collect sub-bots (unique by path)
    seen_paths: set[str] = set()
    sub_bots: list[dict[str, Any]] = []
    for step in mapped_steps:
        path = step.get("subtask_path", "")
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        resolved = path.rstrip("/").split("/")[-1]
        # Check if the bot is present in the package (case-insensitive)
        resolved_key: str | None = None
        for key in all_bots:
            if key.lower() == resolved.lower():
                resolved_key = key
                break
        sub_bots.append({
            "subtask_path": path,
            "resolved_bot_name": resolved_key,
            "xaml_filename": sanitize_filename(resolved) + ".xaml",
        })

    # Error handling detection
    has_error_handling = any(
        s["aa_package"].lower() == "errorhandler" for s in mapped_steps
    )
    error_handling = {
        "detected": has_error_handling,
        "pattern": "TryCatch detected" if has_error_handling else "None detected",
    }

    # External systems
    ext_systems: list[str] = []
    seen_systems: set[str] = set()
    for step in mapped_steps:
        label = _SYSTEM_MAP.get(step["aa_package"].lower())
        if label and label not in seen_systems:
            seen_systems.add(label)
            ext_systems.append(label)

    # NuGet packages (always include System.Activities as base). Versions resolve
    # through the central resolver (overrides > reference_project > table); any
    # unknown package is surfaced via version_warnings instead of silently pinned.
    version_warnings: list[str] = []

    def _resolve(name: str) -> str:
        version, is_fallback = resolve_package_version(
            name, overrides=version_overrides, reference_versions=reference_versions
        )
        if is_fallback:
            msg = (
                f"No pinned version for '{name}'; defaulted to 1.0.0. "
                "Pass package_versions or a reference_project to set it."
            )
            if msg not in version_warnings:
                version_warnings.append(msg)
        return version

    seen_pkgs: set[str] = {"UiPath.System.Activities"}
    nuget_pkgs: list[dict[str, str]] = [
        {"name": "UiPath.System.Activities",
         "version": _resolve("UiPath.System.Activities")}
    ]
    for step in mapped_steps:
        pkg_name = step.get("uipath_package")
        if pkg_name and pkg_name not in seen_pkgs:
            seen_pkgs.add(pkg_name)
            nuget_pkgs.append({"name": pkg_name, "version": _resolve(pkg_name)})
    nuget_pkgs.sort(key=lambda x: x["name"])

    # Packages actually referenced by a MAPPED (typed) activity — these become the
    # project.json dependencies. The rest of nuget_packages are "implied" by the
    # bot's logic but are generated as labelled placeholders, so they are surfaced
    # as documentation, not hard dependencies. System.Activities is always
    # referenced (InvokeWorkflowFile + core WF4).
    ref_names: set[str] = {"UiPath.System.Activities"}
    for step in mapped_steps:
        if step.get("mapping_status") == MAPPED and step.get("uipath_package"):
            ref_names.add(step["uipath_package"])
    referenced_pkgs = [p for p in nuget_pkgs if p["name"] in ref_names]

    # Stats
    active = [s for s in mapped_steps if not s["disabled"]]
    mapped_count  = sum(1 for s in active if s["mapping_status"] == MAPPED)
    partial_count = sum(1 for s in active if s["mapping_status"] == PARTIAL)
    todo_count    = sum(1 for s in active if s["mapping_status"] == TODO)
    ui_count      = sum(1 for s in active
                        if s.get("uipath_package") == "UiPath.UIAutomation.Activities")
    disabled_count = sum(1 for s in mapped_steps if s["disabled"])
    total_active   = len(active)
    coverage_pct   = (
        round((mapped_count + partial_count) / total_active * 100, 1)
        if total_active else 0.0
    )

    stats = {
        "total_steps":            len(mapped_steps),
        "active_steps":           total_active,
        "mapped_count":           mapped_count,
        "partial_count":          partial_count,
        "todo_count":             todo_count,
        "coverage_pct":           coverage_pct,
        "ui_automation_step_count": ui_count,
        "disabled_step_count":    disabled_count,
    }

    input_count  = sum(1 for v in mapped_vars if v["scope"] == "input")
    output_count = sum(1 for v in mapped_vars if v["scope"] == "output")
    overview = (
        f"{bot_name}: {len(mapped_steps)} steps "
        f"({coverage_pct}% mapped), "
        f"{input_count} input variable(s), "
        f"{output_count} output variable(s)"
    )

    return {
        "bot_name":       bot_name,
        "folder_path":    folder_path,
        "overview":       overview,
        "variables":      mapped_vars,
        "steps":          mapped_steps,
        "sub_bots_called": sub_bots,
        "error_handling": error_handling,
        "external_systems": ext_systems,
        "nuget_packages": nuget_pkgs,
        "referenced_packages": referenced_pkgs,
        "version_warnings": version_warnings,
        "stats":          stats,
    }
