"""
UiPath XAML generator.

Converts a structured process summary + raw bot nodes into valid WF4 XAML
that UiPath Studio 25.10 (Windows / .NET target) can open directly.

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
from typing import Any

from aa_mcp.uipath.mapper import (
    MAPPED, PARTIAL, TODO,
    _ASSIGN_COMMANDS,
    lookup_mapping, sanitize_filename,
)

# ── XML namespace declarations ─────────────────────────────────────────────────

# Namespace prefixes mirror what UiPath Studio 25.10 (Windows / .NET) emits.
# NB: modern .NET assemblies — scg/sco resolve from System.Private.CoreLib (NOT
# mscorlib) and sd (System.Data.DataTable) from System.Data.Common (NOT System.Data).
# There is deliberately NO `mva` (Microsoft.VisualBasic.Activities) prefix: the
# legacy mva:VisualBasicSettings block is rejected by 25.10 ("Cannot set unknown
# member ...VisualBasicSettings.ImportedNamespaces"); imports use TextExpression instead.
_XMLNS = (
    'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"'
    ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
    ' xmlns:sap="http://schemas.microsoft.com/netfx/2009/xaml/activities/presentation"'
    ' xmlns:sap2010="http://schemas.microsoft.com/netfx/2010/xaml/activities/presentation"'
    ' xmlns:scg="clr-namespace:System.Collections.Generic;assembly=System.Private.CoreLib"'
    ' xmlns:sco="clr-namespace:System.Collections.ObjectModel;assembly=System.Private.CoreLib"'
    ' xmlns:s="clr-namespace:System;assembly=System.Private.CoreLib"'
    ' xmlns:sd="clr-namespace:System.Data;assembly=System.Data.Common"'
    ' xmlns:ui="http://schemas.uipath.com/workflow/activities"'
    ' xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
)

# Modern imports mechanism (replaces the legacy mva:VisualBasicSettings block).
# The root <Activity> carries VisualBasic.Settings="{x:Null}"; namespace/assembly
# imports are declared here so VB expressions resolve. A lean, dependency-agnostic
# core set — always valid; Studio augments it as activities are added.
_TEXT_EXPRESSION_IMPORTS = """\
  <TextExpression.NamespacesForImplementation>
    <sco:Collection x:TypeArguments="x:String">
      <x:String>System.Activities</x:String>
      <x:String>System.Activities.Statements</x:String>
      <x:String>System.Activities.Expressions</x:String>
      <x:String>System.Activities.Validation</x:String>
      <x:String>System.Activities.XamlIntegration</x:String>
      <x:String>Microsoft.VisualBasic</x:String>
      <x:String>Microsoft.VisualBasic.Activities</x:String>
      <x:String>System</x:String>
      <x:String>System.Collections</x:String>
      <x:String>System.Collections.Generic</x:String>
      <x:String>System.Collections.ObjectModel</x:String>
      <x:String>System.Data</x:String>
      <x:String>System.Diagnostics</x:String>
      <x:String>System.IO</x:String>
      <x:String>System.Linq</x:String>
      <x:String>System.Linq.Expressions</x:String>
      <x:String>System.Net.Mail</x:String>
      <x:String>System.Xml</x:String>
      <x:String>System.Xml.Linq</x:String>
      <x:String>System.Runtime.Serialization</x:String>
      <x:String>UiPath.Core</x:String>
      <x:String>UiPath.Core.Activities</x:String>
    </sco:Collection>
  </TextExpression.NamespacesForImplementation>
  <TextExpression.ReferencesForImplementation>
    <sco:Collection x:TypeArguments="AssemblyReference">
      <AssemblyReference>mscorlib</AssemblyReference>
      <AssemblyReference>Microsoft.VisualBasic</AssemblyReference>
      <AssemblyReference>System</AssemblyReference>
      <AssemblyReference>System.Activities</AssemblyReference>
      <AssemblyReference>System.ComponentModel.TypeConverter</AssemblyReference>
      <AssemblyReference>System.Core</AssemblyReference>
      <AssemblyReference>System.Data</AssemblyReference>
      <AssemblyReference>System.Data.Common</AssemblyReference>
      <AssemblyReference>System.Linq</AssemblyReference>
      <AssemblyReference>System.Linq.Expressions</AssemblyReference>
      <AssemblyReference>System.Net.Mail</AssemblyReference>
      <AssemblyReference>System.ObjectModel</AssemblyReference>
      <AssemblyReference>System.Private.CoreLib</AssemblyReference>
      <AssemblyReference>System.Private.DataContractSerialization</AssemblyReference>
      <AssemblyReference>System.Runtime.Serialization.Primitives</AssemblyReference>
      <AssemblyReference>System.Xaml</AssemblyReference>
      <AssemblyReference>System.Xml</AssemblyReference>
      <AssemblyReference>System.Xml.Linq</AssemblyReference>
      <AssemblyReference>PresentationCore</AssemblyReference>
      <AssemblyReference>PresentationFramework</AssemblyReference>
      <AssemblyReference>WindowsBase</AssemblyReference>
      <AssemblyReference>UiPath.System.Activities</AssemblyReference>
    </sco:Collection>
  </TextExpression.ReferencesForImplementation>"""


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

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append(
        f'<Activity mc:Ignorable="sap sap2010" x:Class="{class_name}"'
        f' VisualBasic.Settings="{{x:Null}}"'
        f' sap2010:WorkflowViewState.IdRef="ActivityBuilder_1"'
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

    # Namespace + assembly imports so VB expressions resolve (modern Windows /
    # .NET form; the legacy mva:VisualBasicSettings block is rejected by 25.10).
    lines.append(_TEXT_EXPRESSION_IMPORTS)

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
        display_name = f"Run {subtask_name}" if subtask_name else label
        lines.append(
            f'{i}<ui:InvokeWorkflowFile'
            f' DisplayName="{_attr(display_name)}"'
            f' WorkflowFileName="{_attr(xaml_file)}" />'
        )
        return

    # ── TaskBot/stopTask → Throw ──────────────────────────────────────────────
    if pkg_l == "taskbot" and cmd_l == "stoptask":
        lines.append(f'{i}<Throw DisplayName="{_attr(label)}" />')
        return

    # ── ErrorHandler/throw → Throw ────────────────────────────────────────────
    if pkg_l == "errorhandler" and cmd_l == "throw":
        # Raise / re-throw (previously mis-mapped to an empty, no-op TryCatch).
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

    # ── Loop control (break / continue) → labelled placeholders ──────────────
    # UiPath Break/Continue are no-config leaf activities, but their exact XAML
    # element isn't emitted here (avoid a guess that could fail to load) — flag
    # them for the developer to drop in. (Previously these became empty ForEach
    # loops, misrepresenting the AA logic.)
    if pkg_l == "loop" and cmd_l in ("loop.commands.break", "break"):
        dn = f"[PARTIAL] {label} | AA: {pkg}.{cmd} | Replace with a UiPath Break activity"
        lines.append(f'{i}<Sequence DisplayName="{_attr(dn)}" />')
        return
    if pkg_l == "loop" and cmd_l in ("loop.commands.continue", "continue"):
        dn = f"[PARTIAL] {label} | AA: {pkg}.{cmd} | Replace with a UiPath Continue activity"
        lines.append(f'{i}<Sequence DisplayName="{_attr(dn)}" />')
        return

    # ── Loop → ForEach ────────────────────────────────────────────────────────
    if pkg_l == "loop":
        _write_for_each(label, pkg, cmd, children, lines, indent)
        return

    # ── If → If (with else-if / else branches) ────────────────────────────────
    if pkg_l == "if":
        _write_if(label, pkg, cmd, children, branches, lines, indent)
        return

    # ── General case: container nodes (have children) ─────────────────────────
    if children:
        mapping = lookup_mapping(pkg, cmd)
        rich_label = _enrich_label(node, label, pkg, cmd)
        if mapping.status == MAPPED:
            dn = rich_label
        elif mapping.status == PARTIAL:
            dn = f"[PARTIAL] {rich_label} | AA: {pkg}.{cmd} | {mapping.notes}"
        else:
            dn = f"[TODO] {rich_label} | AA: {pkg}.{cmd} | {mapping.notes}"
        lines.append(f'{i}<Sequence DisplayName="{_attr(dn)}">')
        _process_nodes(children, lines, indent + 2)
        lines.append(f"{i}</Sequence>")
        return

    # ── Leaf nodes ────────────────────────────────────────────────────────────
    mapping = lookup_mapping(pkg, cmd)
    rich_label = _enrich_label(node, label, pkg, cmd)
    if mapping.status == MAPPED:
        dn = rich_label
    elif mapping.status == PARTIAL:
        dn = f"[PARTIAL] {rich_label} | AA: {pkg}.{cmd} | {mapping.notes}"
    else:
        dn = f"[TODO] {rich_label} | AA: {pkg}.{cmd} | {mapping.notes}"

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
    lines.append(f'{i2}<Catch x:TypeArguments="s:Exception">')
    lines.append(f'{i3}<ActivityAction x:TypeArguments="s:Exception">')
    lines.append(f"{i4}<ActivityAction.Argument>")
    lines.append(
        f'{i5}<DelegateInArgument x:TypeArguments="s:Exception"'
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
    branches: list[dict[str, Any]],
    lines: list[str],
    indent: int,
) -> None:
    """
    Emit a UiPath If. The AA `if` body becomes If.Then; AA else-if / else
    `branches` become the If.Else. A UiPath If is binary (Then/Else), so an AA
    else-if chain is rendered as nested Ifs inside the Else (the terminal AA
    `else` becomes the innermost Else Sequence). Conditions are stubbed as a
    [PARTIAL] placeholder for manual mapping in Studio.
    """
    i0 = _i(indent)
    i1 = _i(indent + 2)
    i2 = _i(indent + 4)
    i3 = _i(indent + 6)

    dn = f"[PARTIAL] {label} | AA: {pkg}.{cmd} | Set condition expression"
    lines.append(f'{i0}<If DisplayName="{_attr(dn)}">')

    # Placeholder false condition (set the real expression in Studio)
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
    _write_else_chain(branches, lines, indent + 4)
    lines.append(f"{i1}</If.Else>")

    lines.append(f"{i0}</If>")


def _write_else_chain(
    branches: list[dict[str, Any]],
    lines: list[str],
    indent: int,
) -> None:
    """
    Render the content of an <If.Else> from an AA else-if / else branch list.
    `else` → a terminal Sequence; `elseIf` → a nested If whose own Else recurses
    into the remaining branches. Guarantees every branch step is emitted — the
    prior generator silently dropped all else / else-if branch steps.
    """
    i0 = _i(indent)
    if not branches:
        lines.append(f'{i0}<Sequence DisplayName="Else" />')
        return

    first, rest = branches[0], branches[1:]
    bcmd = (first.get("command") or "").lower()
    bchildren = first.get("children", [])

    if bcmd == "else":
        if bchildren:
            lines.append(f'{i0}<Sequence DisplayName="Else">')
            _process_nodes(bchildren, lines, indent + 2)
            lines.append(f"{i0}</Sequence>")
        else:
            lines.append(f'{i0}<Sequence DisplayName="Else" />')
        return

    # elseIf (or any non-else branch) → nested If, remaining branches in its Else
    i1 = _i(indent + 2)
    i2 = _i(indent + 4)
    i3 = _i(indent + 6)
    dn = (
        f"[PARTIAL] Else If | AA: If.{first.get('command', 'elseIf')}"
        " | Set condition expression"
    )
    lines.append(f'{i0}<If DisplayName="{_attr(dn)}">')
    lines.append(f"{i1}<If.Condition>")
    lines.append(f'{i2}<InArgument x:TypeArguments="x:Boolean">')
    lines.append(f'{i3}<Literal x:TypeArguments="x:Boolean" Value="False" />')
    lines.append(f"{i2}</InArgument>")
    lines.append(f"{i1}</If.Condition>")
    lines.append(f"{i1}<If.Then>")
    lines.append(f'{i2}<Sequence DisplayName="Then">')
    _process_nodes(bchildren, lines, indent + 6)
    lines.append(f"{i2}</Sequence>")
    lines.append(f"{i1}</If.Then>")
    lines.append(f"{i1}<If.Else>")
    _write_else_chain(rest, lines, indent + 4)
    lines.append(f"{i1}</If.Else>")
    lines.append(f"{i0}</If>")


# ── Label enrichment ──────────────────────────────────────────────────────────

def _enrich_label(
    node: dict[str, Any],
    label: str,
    pkg: str,
    cmd: str,
) -> str:
    """
    Return a more descriptive label for a node where possible.

    - Assign-type commands with output_variables → "Assign → varName"
    - TaskBot/runTask → handled separately in _process_node (uses subtask_path)
    - All others → original label unchanged
    """
    out_vars = node.get("output_variables", [])
    if out_vars and cmd.lower() in _ASSIGN_COMMANDS:
        return f"Assign \u2192 {out_vars[0]}"
    return label


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
