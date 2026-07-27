# Automation Anywhere Control Room MCP Server

The first open-source MCP server for Automation Anywhere Control Room. Connect Claude Code directly to your Control Room to trigger bots, inspect run history, and query WLM queues.

> **Note:** Automation Anywhere released native inbound MCP support in v38 (their platform receives connections from external agents). This server is the reverse: it exposes Control Room as an MCP tool server so Claude and other MCP clients can drive it directly.

## Prerequisites

- Python 3.11+
- Automation Anywhere Control Room with API access enabled
- A service account with:
  - "Run my bots" privilege
  - Bot Runner license
  - AAE_Queue Admin role (for WLM tools)
- Your API key: Control Room > Settings > Profile > API Key

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

## Connect to Claude Code

### Quick setup

After installation, register the server with Claude Code. Replace `/path/to/aa-mcp-server` with the absolute path to your cloned repository.

Or open a Claude Code session and ask it. See [CLAUDE-CODE-INSTALL.md](CLAUDE-CODE-INSTALL.md) for a copy-paste prompt.

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
| `validate_uipath_project` | Validate a generated project folder without UiPath Studio. Checks XML well-formedness, project.json completeness, and all InvokeWorkflowFile references. Run immediately after generate_uipath_template. |

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
| `AA_CONTROL_ROOM_URL` | Yes | — | Base URL, no trailing slash |
| `AA_USERNAME` | Yes | — | Service account username |
| `AA_API_KEY` | Yes | — | 40-character API key |
| `AA_TOKEN_REFRESH_BUFFER_SECONDS` | No | 60 | Seconds before expiry to refresh token |
| `AA_HTTP_TIMEOUT_SECONDS` | No | 30 | Request timeout in seconds |
| `AA_SSL_VERIFY` | No | true | Set to `false` for self-signed certificates |
| `AA_LOG_LEVEL` | No | WARNING | Set to `DEBUG` to log request URLs and response codes to stderr |

## Troubleshooting

**401 errors on startup:**
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
