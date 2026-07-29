#!/usr/bin/env python3
"""
Generate a UiPath project from a synthetic, committable fixture — no AA export ZIP.

Drives the real generator (package_parser + writer.generate_project_files) so
tests/CI exercise the actual code path, with a fixture that carries zero
proprietary bot content. The synthetic master exercises the constructs that have
regressed before: If with elseIf/else branches, ErrorHandler try + throw, a Loop
with break/continue, a TaskBot/runTask sub-bot call, every variable type, and a
disabled node. Used by .github/workflows/uipath-validate.yml.

Usage:  python scripts/gen_fixture.py <output_dir>
"""

from __future__ import annotations

import asyncio
import sys

from aa_mcp import package_parser
from aa_mcp.uipath import writer

# ── Synthetic raw A360 bot definitions (packageName/commandName node schema) ────

_MASTER = {
    "variables": [
        {"name": "in_TicketId", "type": "STRING", "input": True, "inputRequired": True},
        {"name": "out_Result", "type": "STRING", "output": True},
        {"name": "v_Count", "type": "NUMBER"},
        {"name": "v_When", "type": "DATETIME"},
        {"name": "v_Items", "type": "LIST"},
        {"name": "v_Map", "type": "DICTIONARY"},
        {"name": "v_Table", "type": "TABLE"},
    ],
    "packages": [],
    "nodes": [
        {"packageName": "Step", "commandName": "step",
         "attributes": [{"name": "title", "value": {"string": "Initialize"}}],
         "children": [
             {"packageName": "String", "commandName": "assign",
              "returnTo": {"variableName": "out_Result"}},
         ]},
        # If with an elseIf and an else — the class that used to be silently dropped
        {"packageName": "If", "commandName": "if",
         "children": [
             {"packageName": "String", "commandName": "assign",
              "returnTo": {"variableName": "out_Result"}},
         ],
         "branches": [
             {"packageName": "If", "commandName": "elseIf",
              "children": [
                  {"packageName": "Number", "commandName": "increment",
                   "returnTo": {"variableName": "v_Count"}},
              ]},
             {"packageName": "If", "commandName": "else",
              "children": [
                  {"packageName": "Email", "commandName": "sendMailV2"},
              ]},
         ]},
        # ErrorHandler try, with a catch branch that re-throws
        {"packageName": "ErrorHandler", "commandName": "try",
         "children": [
             {"packageName": "TaskBot", "commandName": "runTask",
              "attributes": [{"name": "taskbot", "value": {
                  "taskbotFile": {"string": "repository:///Bots/Fixtures/SubFixture"}}}]},
         ],
         "branches": [
             {"packageName": "ErrorHandler", "commandName": "catch",
              "children": [
                  {"packageName": "ErrorHandler", "commandName": "throw"},
              ]},
         ]},
        # Loop with break + continue in the body, and a DataTable op
        {"packageName": "Loop", "commandName": "loop.commands.start",
         "children": [
             {"packageName": "DataTable", "commandName": "assign",
              "returnTo": {"variableName": "v_Table"}},
             {"packageName": "Loop", "commandName": "loop.commands.continue"},
             {"packageName": "Loop", "commandName": "loop.commands.break"},
         ]},
        {"packageName": "TaskBot", "commandName": "stopTask"},
        {"packageName": "LogToFile", "commandName": "writeToFile", "disabled": True},
    ],
}

_SUB = {
    "variables": [
        {"name": "in_Path", "type": "STRING", "input": True},
        {"name": "out_Ok", "type": "BOOLEAN", "output": True},
    ],
    "packages": [],
    "nodes": [
        {"packageName": "Step", "commandName": "step",
         "attributes": [{"name": "title", "value": {"string": "Sub body"}}],
         "children": [
             {"packageName": "Excel", "commandName": "readRange",
              "returnTo": {"variableName": "out_Ok"}},
             {"packageName": "WebServices", "commandName": "restPost"},
         ]},
    ],
}


def _contents() -> dict:
    master = package_parser._parse_bot(_MASTER, "Automation Anywhere/Bots/Fixtures/MasterFixture")
    sub = package_parser._parse_bot(_SUB, "Automation Anywhere/Bots/Fixtures/SubFixture")
    return {
        "bots": {master["name"]: master, sub["name"]: sub},
        "manifest": {}, "parse_warnings": [], "zip_summary": {},
    }


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "fixture_out"
    report = asyncio.run(
        writer.generate_project_files("", "MasterFixture", out, contents=_contents())
    )
    if "error" in report:
        print(f"generation error: {report['error']}", file=sys.stderr)
        return 1
    print(f"Generated project at: {report['output_path']}")
    print(f"Files: {report['files_written']}")
    if report.get("warnings"):
        print(f"Warnings: {report['warnings']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
