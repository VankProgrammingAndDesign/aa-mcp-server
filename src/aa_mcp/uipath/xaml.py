"""
UiPath XAML generator.

Converts a structured process summary + raw bot nodes into valid WF4 XAML
that UiPath Studio 2024.10 can open directly.

Uses string-based generation (not ElementTree) to maintain full control
over namespace declarations and attribute ordering.

Mapping status in generated DisplayNames:
  [PARTIAL] — activity type known; parameters need manual mapping in Studio
  [TODO]    — no meaningful mapping; implement manually
  [DISABLED] — step was disabled in the original AA bot
  [STUB]    — sub-bot not present in the export package
"""

from __future__ import annotations

import html
from urllib.parse import unquote
from typing import Any

from aa_mcp.uipath.mapper import (
    MAPPED, PARTIAL, TODO,
    lookup_mapping, sanitize_filename,
)

# ── XML namespace declarations ─────────────────────────────────────────────────

_XMLNS = (
    'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"'
    ' xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
    ' xmlns:ui="http://schemas.uipath.com/workflow/activities"'
    ' xmlns:sap="http://schemas.microsoft.com/netfx/2009/xaml/activities/presentation"'
    ' xmlns:sap2010="http://schemas.microsoft.com/netfx/2010/xaml/activities/presentation"'
    ' xmlns:mva="clr-namespace:Microsoft.VisualBasic.Activities;assembly=System.Activities"'
    ' xmlns:scg="clr-namespace:System.Collections.Generic;assembly=mscorlib"'
    ' xmlns:sd="clr-namespace:System.Data;assembly=System.Data"'
    ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)

_VB_SETTINGS = """\
  <mva:VisualBasic.Settings>
    <mva:VisualBasicSettings>
      <mva:VisualBasicSettings.ImportedNamespaces>
        <mva:VisualBasicImportReference Assembly="mscorlib" Import="System" />
        <mva:VisualBasicImportReference Assembly="mscorlib" Import="System.Collections.Generic" />
        <mva:VisualBasicImportReference Assembly="System.Core" Import="System.Linq" />
        <mva:VisualBasicImportReference Assembly="System.Data" Import="System.Data" />
      </mva:VisualBasicSettings.ImportedNamespaces>
    </mva:VisualBasicSettings>
  </mva:VisualBasic.Settings>"""


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_workflow_xaml(
    summary: dict[str, Any],
    workflow_name: str,
    structured_nodes: list[dict[str, Any]],
    is_stub: bool = False,
) -> str:
    """
    Generate a complete UiPath XAML workflow string.

    Parameters
    ----------
    summary:          ProcessSummary from mapper.build_process_summary().
    workflow_name:    Name used for x:Class and root Sequence DisplayName.
    structured_nodes: Output of package_parser.build_structure() for this bot.
    is_stub:          If True, generates a minimal stub (sub-bot not in package).

    Returns the full XAML string with XML declaration.
    """
    class_name = sanitize_filename(workflow_name)
    variables = summary.get("variables", [])
    error_handling = summary.get("error_handling", {})
    has_try_catch = error_handling.get("detected", False)

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append(
        f'<Activity mc:Ignorable="sap sap2010" x:Class="{class_name}"'
    )
    lines.append(f'  {_XMLNS}>')

    # Arguments (input/output/workItem variables become x:Members)
    args = [v for v in variables if v.get("uipath_direction")]
    if args:
        lines.append("  <x:Members>")
        for v in args:
            direction = v["uipath_direction"]
            uitype = v["uipath_type"]
            name = _safe_name(v["name"])
            lines.append(
                f'    <x:Property Name="{name}"'
                f' Type="{direction}Argument({uitype})" />'
            )
        lines.append("  </x:Members>")

    # VisualBasic settings (needed for VB expressions to resolve)
    lines.append(_VB_SETTINGS)

    # Root Sequence
    lines.append(f'  <Sequence DisplayName="{_attr(workflow_name)}">')

    # Local variables
    locals_ = [v for v in variables if v.get("uipath_direction") is None]
    if locals_:
        lines.append("    <Sequence.Variables>")
        for v in locals_:
            uitype = v["uipath_type"]
            name = _safe_name(v["name"])
            lines.append(
                f'      <Variable x:TypeArguments="{uitype}" Name="{name}" />'
            )
        lines.append("    </Sequence.Variables>")

    if is_stub:
        lines.append(
            f'    <Sequence DisplayName="[STUB] {_attr(workflow_name)}'
            f' — implement manually" />'
        )
    else:
        # Generate activity elements from structured nodes
        _process_nodes(structured_nodes, lines, indent=4)

    lines.append("  </Sequence>")
    lines.append("</Activity>")
    return "\n".join(lines)


# ── Recursive node processor ───────────────────────────────────────────────────

def _process_nodes(
    nodes: list[dict[str, Any]],
    lines: list[str],
    indent: int,
) -> None:
    """Recursively convert structured bot nodes to XAML activity elements."""
    for node in nodes:
        _process_node(node, lines, indent)


def _process_node(
    node: dict[str, Any],
    lines: list[str],
    indent: int,
) -> None:
    pkg = node.get("package", "")
    cmd = node.get("command", "")
    label = node.get("label", "") or cmd or pkg
    disabled = node.get("disabled", False)
    children = node.get("children", [])
    branches = node.get("branches", [])

    i = _i(indent)

    if disabled:
        dn = f"[DISABLED] {label}"
        if children:
            lines.append(f'{i}<Sequence DisplayName="{_attr(dn)}">')
            _process_nodes(children, lines, indent + 2)
            lines.append(f"{i}</Sequence>")
        else:
            lines.append(f'{i}<Sequence DisplayName="{_attr(dn)}" />')
        return

    pkg_l = pkg.lower()
    cmd_l = cmd.lower()

    # ── TaskBot/runTask → InvokeWorkflowFile ──────────────────────────────────
    if pkg_l == "taskbot" and cmd_l == "runtask":
        subtask_path = node.get("subtask_path", "")
        subtask_name = (
            subtask_path.rstrip("/").split("/")[-1]
            if subtask_path else label
        )
        xaml_file = sanitize_filename(subtask_name) + ".xaml"
        lines.append(
            f'{i}<ui:InvokeWorkflowFile'
            f' DisplayName="{_attr(label)}"'
            f' WorkflowFileName="{_attr(xaml_file)}" />'
        )
        return

    # ── TaskBot/stopTask → Throw ──────────────────────────────────────────────
    if pkg_l == "taskbot" and cmd_l == "stoptask":
        lines.append(f'{i}<Throw DisplayName="{_attr(label)}" />')
        return

    # ── ErrorHandler/try → TryCatch ───────────────────────────────────────────
    if pkg_l == "errorhandler":
        _write_try_catch(label, children, branches, lines, indent)
        return

    # ── Step / Comment → Sequence container ──────────────────────────────────
    if pkg_l in ("step", "comment") or (
        pkg_l == "" and children
    ):
        if children:
            lines.append(f'{i}<Sequence DisplayName="{_attr(label)}">')
            _process_nodes(children, lines, indent + 2)
            lines.append(f"{i}</Sequence>")
        else:
            lines.append(f'{i}<Sequence DisplayName="{_attr(label)}" />')
        return

    # ── Loop → ForEach ────────────────────────────────────────────────────────
    if pkg_l == "loop":
        _write_for_each(label, pkg, cmd, children, lines, indent)
        return

    # ── If → If ───────────────────────────────────────────────────────────────
    if pkg_l == "if":
        _write_if(label, pkg, cmd, children, lines, indent)
        return

    # ── General case: container nodes (have children) ─────────────────────────
    if children:
        mapping = lookup_mapping(pkg, cmd)
        if mapping.status == MAPPED:
            dn = label
        elif mapping.status == PARTIAL:
            dn = f"[PARTIAL] {label} | AA: {pkg}.{cmd} | {mapping.notes}"
        else:
            dn = f"[TODO] {label} | AA: {pkg}.{cmd} | {mapping.notes}"
        lines.append(f'{i}<Sequence DisplayName="{_attr(dn)}">')
        _process_nodes(children, lines, indent + 2)
        lines.append(f"{i}</Sequence>")
        return

    # ── Leaf nodes ────────────────────────────────────────────────────────────
    mapping = lookup_mapping(pkg, cmd)
    if mapping.status == MAPPED:
        dn = label
    elif mapping.status == PARTIAL:
        dn = f"[PARTIAL] {label} | AA: {pkg}.{cmd} | {mapping.notes}"
    else:
        dn = f"[TODO] {label} | AA: {pkg}.{cmd} | {mapping.notes}"

    lines.append(f'{i}<Sequence DisplayName="{_attr(dn)}" />')


# ── Structural activity writers ────────────────────────────────────────────────

def _write_try_catch(
    label: str,
    children: list[dict[str, Any]],
    branches: list[dict[str, Any]],
    lines: list[str],
    indent: int,
) -> None:
    i0 = _i(indent)
    i1 = _i(indent + 2)
    i2 = _i(indent + 4)
    i3 = _i(indent + 6)
    i4 = _i(indent + 8)
    i5 = _i(indent + 10)

    lines.append(f'{i0}<TryCatch DisplayName="TryCatch">')
    lines.append(f"{i1}<TryCatch.Try>")
    lines.append(f'{i2}<Sequence DisplayName="Try Block">')
    _process_nodes(children, lines, indent + 6)
    lines.append(f"{i2}</Sequence>")
    lines.append(f"{i1}</TryCatch.Try>")

    lines.append(f"{i1}<TryCatch.Catches>")
    lines.append(f'{i2}<Catch x:TypeArguments="x:Exception">')
    lines.append(f'{i3}<ActivityAction x:TypeArguments="x:Exception">')
    lines.append(f"{i4}<ActivityAction.Argument>")
    lines.append(
        f'{i5}<DelegateInArgument x:TypeArguments="x:Exception"'
        f' Name="exception" />'
    )
    lines.append(f"{i4}</ActivityAction.Argument>")
    lines.append(
        f'{i4}<Sequence DisplayName="[TODO] Handle Exception'
        f' — review AA ErrorHandler branches">'
    )
    for branch in branches:
        _process_nodes(branch.get("children", []), lines, indent + 10)
    lines.append(f"{i4}</Sequence>")
    lines.append(f"{i3}</ActivityAction>")
    lines.append(f"{i2}</Catch>")
    lines.append(f"{i1}</TryCatch.Catches>")
    lines.append(f"{i0}</TryCatch>")


def _write_for_each(
    label: str,
    pkg: str,
    cmd: str,
    children: list[dict[str, Any]],
    lines: list[str],
    indent: int,
) -> None:
    i0 = _i(indent)
    i1 = _i(indent + 2)
    i2 = _i(indent + 4)
    i3 = _i(indent + 6)

    dn = f"[PARTIAL] {label} | AA: {pkg}.{cmd} | Bind collection and item variable"
    lines.append(
        f'{i0}<ForEach x:TypeArguments="x:Object"'
        f' DisplayName="{_attr(dn)}">'
    )
    lines.append(f'{i1}<ActivityAction x:TypeArguments="x:Object">')
    lines.append(f"{i2}<ActivityAction.Argument>")
    lines.append(
        f'{i3}<DelegateInArgument x:TypeArguments="x:Object" Name="item" />'
    )
    lines.append(f"{i2}</ActivityAction.Argument>")
    lines.append(f'{i2}<Sequence DisplayName="Loop Body">')
    _process_nodes(children, lines, indent + 8)
    lines.append(f"{i2}</Sequence>")
    lines.append(f"{i1}</ActivityAction>")
    lines.append(f"{i0}</ForEach>")


def _write_if(
    label: str,
    pkg: str,
    cmd: str,
    children: list[dict[str, Any]],
    lines: list[str],
    indent: int,
) -> None:
    i0 = _i(indent)
    i1 = _i(indent + 2)
    i2 = _i(indent + 4)
    i3 = _i(indent + 6)

    dn = f"[PARTIAL] {label} | AA: {pkg}.{cmd} | Set condition expression"
    lines.append(f'{i0}<If DisplayName="{_attr(dn)}">')

    # Placeholder false condition
    lines.append(f"{i1}<If.Condition>")
    lines.append(f'{i2}<InArgument x:TypeArguments="x:Boolean">')
    lines.append(f'{i3}<Literal x:TypeArguments="x:Boolean" Value="False" />')
    lines.append(f"{i2}</InArgument>")
    lines.append(f"{i1}</If.Condition>")

    lines.append(f"{i1}<If.Then>")
    lines.append(f'{i2}<Sequence DisplayName="Then">')
    _process_nodes(children, lines, indent + 6)
    lines.append(f"{i2}</Sequence>")
    lines.append(f"{i1}</If.Then>")

    lines.append(f"{i1}<If.Else>")
    lines.append(f'{i2}<Sequence DisplayName="[TODO] Else Block" />')
    lines.append(f"{i1}</If.Else>")

    lines.append(f"{i0}</If>")


# ── String helpers ─────────────────────────────────────────────────────────────

def _i(n: int) -> str:
    """Return n spaces for indentation."""
    return " " * n


def _attr(value: str) -> str:
    """Escape a string for use in an XML attribute value."""
    return html.escape(str(value), quote=True)


def _safe_name(name: str) -> str:
    """Ensure a variable/argument name is a valid XML NCName."""
    import re
    safe = re.sub(r"[^\w]", "_", name)
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return safe or "var"
