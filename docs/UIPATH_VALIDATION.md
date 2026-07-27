# UiPath Code Generation — Validation Checklist

The AA→UiPath code generation (v0.3.0) produces UiPath projects — `project.json`,
one `.xaml` per bot, `PDD.md`, and `ARCHITECTURE.md` — that **pass the built-in
structural validator** (`validate_uipath_project`): well-formed XAML, a complete
`project.json`, and resolvable `InvokeWorkflowFile` references.

What it does **not** yet prove is runtime behaviour in a real UiPath Studio /
robot. This checklist tracks that validation; each item is a GitHub issue.

> **Status:** analysis & PDD generation are proven on real exports. The UiPath
> output is a **working starting point that still needs a live UiPath instance to
> confirm** — treat it as a scaffold to test, not code to ship.

## Needs a live UiPath Studio / robot

- [ ] [#1](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/1) — Open a generated project in UiPath Studio 2024.10
- [ ] [#2](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/2) — Verify pinned NuGet dependency versions resolve
- [ ] [#3](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/3) — Confirm all generated XAML opens without load errors
- [ ] [#4](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/4) — Confirm master→sub-bot `InvokeWorkflowFile` wiring
- [ ] [#5](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/5) — Review `[PARTIAL]` activity-type choices for correctness
- [ ] [#6](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/6) — Run the smallest generated bot end-to-end

## Test infrastructure (no UiPath instance needed)

- [ ] [#7](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/7) — Add secret-free synthetic bot-export fixtures
- [ ] [#8](https://github.com/VankProgrammingAndDesign/aa-mcp-server/issues/8) — Add unit / golden-file tests for mapper, docgen, validator (depends on #7)

## Generate a project to validate against

In Claude Code, with the MCP server connected:

```
"Generate a UiPath template from <bot name> in <export.zip> to ./out"
"Validate the UiPath project at ./out"
```

…or call the tools directly: `generate_uipath_template(zip_path, bot_name, output_path)`
then `validate_uipath_project(output_path)`.

## Where the relevant code lives

| Area | File |
|---|---|
| Activity map + NuGet version pins | `src/aa_mcp/uipath/mapper.py` (`ACTIVITY_MAP`, `NUGET_VERSIONS`) |
| XAML generation | `src/aa_mcp/uipath/xaml.py` |
| PDD / architecture docs | `src/aa_mcp/uipath/docgen.py` |
| Structural validator | `src/aa_mcp/tools/uipath_validator.py` |

Issues are labelled [`uipath-validation`](https://github.com/VankProgrammingAndDesign/aa-mcp-server/labels/uipath-validation)
or [`test-infra`](https://github.com/VankProgrammingAndDesign/aa-mcp-server/labels/test-infra).
