#!/usr/bin/env python3
"""
CI gate helper — run a validation layer against an already-generated project dir
and exit non-zero on failure. Cross-platform (no shell quoting), used by
.github/workflows/uipath-validate.yml after scripts/gen_fixture.py.

Usage:
  python scripts/ci_check.py static  <project_dir>   # Layer 1: pure-Python static checks
  python scripts/ci_check.py compile <project_dir>   # Layer 2: real compile via UiPath CLI
"""

from __future__ import annotations

import asyncio
import json
import sys


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("static", "compile"):
        print(__doc__)
        return 2
    mode, project_dir = sys.argv[1], sys.argv[2]

    if mode == "static":
        from aa_mcp.tools.uipath_validator import validate_uipath_project
        report = asyncio.run(validate_uipath_project(project_dir))
        print(json.dumps(report, indent=2))
        return 0 if report["valid"] else 1

    from aa_mcp.tools.uipath_compile import compile_check_uipath_project
    report = asyncio.run(compile_check_uipath_project(project_dir))
    print(json.dumps(report, indent=2))
    # The compile gate passes only on a real, successful build.
    return 0 if (report.get("available") and report.get("ran") and report.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
