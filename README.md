# Automation Anywhere Control Room MCP Server

The first open-source MCP server for Automation Anywhere Control Room. Connect Claude Code directly to your Control Room to trigger bots, inspect run history, and query WLM queues.

> **Note:** Automation Anywhere released native inbound MCP support in v38 (their platform receives connections from external agents). This server is the reverse: it exposes Control Room as an MCP tool server so Claude and other MCP clients can drive it directly.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed — the primary way to install and run this server. See that guide for Claude Code setup; this README does not cover it.
- Python 3.11+
- **For the Control Room tools only:** Automation Anywhere Control Room with API access enabled, and a service account with:
  - "Run my bots" privilege
  - Bot Runner license
  - AAE_Queue Admin role (for WLM tools)
  - Your API key: Control Room > Settings > Profile > API Key

> The Bot Package Analysis and UiPath Migration tools need none of the Automation Anywhere items above — see [Setup without a Control Room](#setup-without-a-control-room-offline--analysis-only).

## Installation

```bash
git clone https://github.com/VankProgrammingAndDesign/aa-mcp-server.git
cd aa-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```
AA_CONTROL_ROOM_URL=https://your-tenant.automationanywhere.digital
AA_USERNAME=your.username@company.com
AA_API_KEY=your-40-character-api-key
```

## Setup without a Control Room (offline / analysis-only)

The **Bot Package Analysis** and **UiPath Migration** tools run entirely on local A360 export ZIPs — no Control Room connection, credentials, or network. If that's all you need, skip real credentials.

Just **omit** the `AA_*` credentials — the server starts without them:

```bash
claude mcp add --scope user automation-anywhere \
  -- /path/to/aa-mcp-server/.venv/bin/aa-mcp-server
```

(Or ask Claude Code to register it with no credentials.) The Control Room tools (`list_bots`, `deploy_bot`, queues, run history) return a clear "credentials not configured" error until you set `AA_CONTROL_ROOM_URL`, `AA_USERNAME`, and `AA_API_KEY`; the analysis and migration tools work regardless.

## Connect to Claude Code

Claude Code is the primary way to install and run this server. Install Claude Code first if you haven't — see the [Claude Code installation guide](https://docs.anthropic.com/en/docs/claude-code) (this README does not cover installing Claude Code itself).

### Recommended: ask Claude Code to register it

After cloning and installing (above), open a Claude Code session and paste this prompt, filling in your values. Use the absolute path to your cloned repo.

```
Add the aa-mcp-server MCP to my Claude Code config:
- Server binary: /path/to/aa-mcp-server/.venv/bin/aa-mcp-server
- AA_CONTROL_ROOM_URL: https://your-tenant.automationanywhere.digital
- AA_USERNAME: your.username@company.com
- AA_API_KEY: your-40-character-api-key
Register it as "automation-anywhere" with --scope user.
```

Claude Code runs `claude mcp add` for you. Full walkthrough: [CLAUDE-CODE-INSTALL.md](CLAUDE-CODE-INSTALL.md).

### Manual: run the command yourself

Replace `/path/to/aa-mcp-server` with the absolute path to your cloned repository.

```bash
claude mcp add --scope user automation-anywhere \
  --env AA_CONTROL_ROOM_URL=https://your-tenant.automationanywhere.digital \
  --env AA_USERNAME=your.username@company.com \
  --env AA_API_KEY=your-40-character-api-key \
  -- /path/to/aa-mcp-server/.venv/bin/aa-mcp-server
```

`--scope user` writes to `~/.claude.json`, making the server available across all your Claude Code projects.

### Verify

Open a Claude Code session and run `/mcp`. You should see `automation-anywhere` listed as `connected`.

### Manual configuration

Add the following to `~/.claude.json` (user-level) or `.mcp.json` in your project root (project-level):

```json
{
  "mcpServers": {
    "automation-anywhere": {
      "command": "/path/to/aa-mcp-server/.venv/bin/aa-mcp-server",
      "env": {
        "AA_CONTROL_ROOM_URL": "https://your-tenant.automationanywhere.digital",
        "AA_USERNAME": "your.username@company.com",
        "AA_API_KEY": "your-40-character-api-key"
      }
    }
  }
}
```

See [CLAUDE-CODE-INSTALL.md](CLAUDE-CODE-INSTALL.md) for a Claude Code-specific walkthrough, or [INSTALL.md](INSTALL.md) for the full guide.

## Available Tools

### Control Room

| Tool | Description |
|---|---|
| `list_bots` | List available bots, with optional name filter |
| `list_devices` | List bot runner devices and their status |
| `deploy_bot` | Trigger a bot on a specific device |
| `list_running_automations` | See what is running right now |
| `list_run_history` | Query past runs by bot name, status, or date range |
| `list_queues` | List WLM queues with item counts by status |
| `get_queue_detail` | Get work items from a specific queue |

### Bot Package Analysis

These tools parse local A360 export ZIP files. No Control Room connection required.

| Tool | Description |
|---|---|
| `load_bot_package` | Load an A360 export ZIP and return bot names, packages in use, and file counts. Call this first. |
| `list_bot_actions` | List all actions in a bot in execution order, with depth, package, command, and subtask paths |
| `get_bot_variables` | Get all variables defined in a bot with types, scope, and default values |
| `get_bot_structure` | Get the full nested action hierarchy including attributes and error handler branches |
| `search_bot_actions` | Search all bots in a package for actions matching a package or command name |

### UiPath Migration

Convert AA bots to UiPath project templates. No Control Room connection required. The output is a working starting point — mapped steps get real WF4 activities, unmapped steps become `[PARTIAL]` or `[TODO]` Sequence placeholders that are visible and labelled in Studio.

| Tool | Description |
|---|---|
| `summarize_bot_process` | Parse an AA bot and return variable mappings with UiPath types, step-by-step activity mappings with status, sub-bots called, external systems, NuGet requirements, and coverage stats. Call this before generating to inspect the mapping. |
| `generate_uipath_template` | Convert an AA bot to a complete UiPath project folder (project.json + XAML files) ready to open in Studio. Sub-bots present in the ZIP get full workflows; missing ones get stub files. |
| `validate_uipath_project` | **Static** validation without UiPath Studio (pure Python, runs anywhere). Checks XML well-formedness, project.json completeness + schemaVersion + dependency bracket notation, InvokeWorkflowFile references, the modern `VisualBasic.Settings="{x:Null}"` + TextExpression imports (no legacy `mva` block), and that every type argument uses a declared prefix with valid `x:` intrinsics (catches `x:Exception`/`x:DateTime`). Run immediately after generate_uipath_template. |
| `compile_check_uipath_project` | **Compile/load gate** — actually builds/packs the project with a UiPath CLI to catch load, NuGet-restore, and activity-type errors the static validator can't. **Requires a Windows host + a UiPath CLI** (`uip`/`uipcli`); Windows-target projects build only on Windows. On macOS/Linux or without a CLI it returns `available: false` with a clear reason (never fails). No license/auth needed. |

> **UiPath output is experimental.** It passes the static validator; `compile_check_uipath_project` adds a real compile gate where a Windows + CLI host is available. Validation tasks are tracked in [`docs/UIPATH_VALIDATION.md`](docs/UIPATH_VALIDATION.md) and the [`uipath-validation`](https://github.com/VankProgrammingAndDesign/aa-mcp-server/labels/uipath-validation) issues.

## Example Prompts

**Trigger a bot:**
> "Run the invoice processor bot on RUNNER-PC-01"

Claude calls `list_bots` to find the bot ID, `list_devices` to find the device ID, then calls `deploy_bot`.

**Check what is running:**
> "What automations are running right now?"

**Investigate failures:**
> "Show me failed runs from the last 7 days"
> "What failed in the invoice queue today?"

**Queue reporting:**
> "Give me a status summary of all WLM queues"
> "Show me the failed items in the AP Processing queue"

**Analyze a bot package:**
> "Load the bot package at /path/to/Export.zip and summarize the overall process"
> "What subtasks does MasterBot call, and in what order?"
> "What are the input and output variables for SubTask_Login?"
> "Show me all the FTP upload actions across every bot in this package"
> "Walk me through the error handling structure in this bot"

**Convert to UiPath:**
> "Summarize MasterTask for UiPath migration"
> "Generate a UiPath template from MasterTask and write it to ~/Desktop/uipath-output"
> "What steps will need manual work after conversion?"

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AA_CONTROL_ROOM_URL` | Control Room tools only | — | Base URL, no trailing slash |
| `AA_USERNAME` | Control Room tools only | — | Service account username |
| `AA_API_KEY` | Control Room tools only | — | 40-character API key |
| `AA_TOKEN_REFRESH_BUFFER_SECONDS` | No | 60 | Seconds before expiry to refresh token |
| `AA_HTTP_TIMEOUT_SECONDS` | No | 30 | Request timeout in seconds |
| `AA_SSL_VERIFY` | No | true | Set to `false` for self-signed certificates |
| `AA_LOG_LEVEL` | No | WARNING | Set to `DEBUG` to log request URLs and response codes to stderr |

## Troubleshooting

**401 errors when calling a Control Room tool:**
Check that `AA_API_KEY` is correct and API access is enabled in Control Room settings.

**Bot not found:**
Call `list_bots` with no filter to see all available bots, then match the exact name.

**deploy_bot returns 400:**
`run_as_user_id` must be the numeric user ID for the device's credential mapping. Find it in Control Room > Devices.

**WLM tools return a permission error:**
The service account needs the `AAE_Queue Admin` role. Add it in Control Room > Roles.

**SSL certificate errors:**
Set `AA_SSL_VERIFY=false` in `.env` or pass `--env AA_SSL_VERIFY=false` to the `claude mcp add` command. Use this only on internal networks where you control the server.

**Enable debug logging:**
Set `AA_LOG_LEVEL=DEBUG` to log all request URLs and response codes to stderr.

## License

MIT
