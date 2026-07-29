"""
Optional compile / load check for a generated UiPath project (the "Layer 2" gate).

Shells out to a UiPath CLI to actually compile/pack the project — catching load,
NuGet-restore, and activity-type-resolution errors that the pure-Python static
validator (validate_uipath_project) cannot.

REQUIREMENTS — this is host-dependent by design:
  * A UiPath CLI on PATH: the new cross-platform `uip` (`uip rpa build`) or the
    legacy `uipcli` (`uipcli package pack`). Set AA_UIPATH_CLI to a custom path.
  * A **Windows host** for Windows-target projects. UiPath builds/packs a project
    whose project.json has targetFramework "Windows" only on Windows, regardless
    of the CLI. On macOS/Linux this returns available=False rather than failing.

When the toolchain isn't present (e.g. on macOS with no CLI) the tool returns
available=False with a clear reason — it never raises. Restore happens against
UiPath's anonymous public feed; no license or Orchestrator auth is required.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PACK_TIMEOUT_SECONDS = 900


async def compile_check_uipath_project(
    output_path: str,
    cli_path: str | None = None,
) -> dict[str, Any]:
    """
    Compile-check a generated UiPath project via a UiPath CLI (Layer 2 gate).

    output_path: directory written by generate_uipath_template.
    cli_path:    optional explicit path to `uip`/`uipcli` (else PATH / AA_UIPATH_CLI).

    Returns a dict with `available` (was the toolchain usable here), `ran`, and —
    when it ran — `success`, `exit_code`, `command`, and `output_tail`. Never raises.
    """
    return await asyncio.to_thread(_compile_check, output_path, cli_path)


def _compile_check(output_path: str, cli_path: str | None) -> dict[str, Any]:
    directory = Path(output_path).resolve()
    pj = directory / "project.json"
    if not pj.exists():
        return {"available": False, "ran": False,
                "reason": f"project.json not found in {output_path}"}

    try:
        target = str(json.loads(pj.read_text(encoding="utf-8")).get("targetFramework", ""))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "ran": False,
                "reason": f"Could not read project.json: {exc}"}

    # Locate a CLI: explicit arg → env var → `uip` → `uipcli`.
    cli = (cli_path or os.environ.get("AA_UIPATH_CLI")
           or shutil.which("uip") or shutil.which("uipcli"))
    if not cli:
        return {"available": False, "ran": False,
                "reason": "No UiPath CLI found on PATH (looked for 'uip' and 'uipcli'). "
                          "Install UiPath.CLI to enable compile validation, or set "
                          "AA_UIPATH_CLI to its path."}

    # Windows-target projects only build/pack on a Windows host.
    if target.lower() == "windows" and platform.system() != "Windows":
        return {"available": False, "ran": False,
                "reason": f"project.json targetFramework is 'Windows', which UiPath "
                          f"builds/packs only on a Windows host; this host is "
                          f"{platform.system()}. Run the compile check on Windows."}

    cli_name = Path(cli).stem.lower()
    with tempfile.TemporaryDirectory() as tmp:
        if cli_name == "uip":
            cmd = [cli, "rpa", "build", str(directory)]
        else:  # legacy uipcli
            # Pass the project FOLDER (absolute), not project.json: uipcli 25.10's
            # workspace/telemetry discovery runs Directory.GetDirectories() on this
            # arg, which throws DirectoryNotFoundException if handed a file path.
            cmd = [cli, "package", "pack", str(directory), "-o", tmp]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=_PACK_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"available": True, "ran": False,
                    "reason": f"CLI invocation failed: {exc}", "command": " ".join(cmd)}

    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return {
        "available": True,
        "ran": True,
        "success": proc.returncode == 0,
        "exit_code": proc.returncode,
        "cli": cli,
        "command": " ".join(cmd),
        "output_tail": "\n".join(combined.splitlines()[-40:]),
    }
