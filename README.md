# Automation Anywhere Control Room MCP Server

A Model Context Protocol (MCP) server for the Automation Anywhere Control Room API. Connect Claude to your AA environment to trigger bots, check run history, and query WLM queues using natural language.

## Prerequisites

- Python 3.11+
- Automation Anywhere Control Room with API access enabled
- A service account with:
  - "Run my bots" privilege
  - Bot Runner access
  - AAE_Queue Admin role (for WLM tools)
- Your API key: Control Room → Settings → Profile → API Key

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

Add to your Claude Code MCP config (`~/.claude/claude_desktop_config.json` or via `/mcp`):

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

## Available Tools

| Tool | Description |
|---|---|
| `list_bots` | List available bots, optionally filtered by name |
| `list_devices` | List bot runner devices and their status |
| `deploy_bot` | Trigger a bot on a specific device |
| `list_running_automations` | See what's running right now |
| `list_run_history` | Query past runs by bot name, status, or date range |
| `list_queues` | List WLM queues with item counts by status |
| `get_queue_detail` | Get individual work items from a queue |

## Example Prompts

**Trigger a bot:**
> "Run the invoice processor bot on RUNNER-PC-01"

Claude will call `list_bots`, find the matching ID, call `list_devices`, find the device ID, then call `deploy_bot`.

**Check what's running:**
> "What automations are running right now?"

**Investigate failures:**
> "Show me failed runs from the last 7 days"
> "What failed in the invoice queue today?"

**Queue reporting:**
> "Give me a status summary of all WLM queues"
> "Show me the failed items in the AP Processing queue"

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AA_CONTROL_ROOM_URL` | Yes | — | Base URL, no trailing slash |
| `AA_USERNAME` | Yes | — | Service account username |
| `AA_API_KEY` | Yes | — | 40-character API key |
| `AA_TOKEN_REFRESH_BUFFER_SECONDS` | No | 60 | Seconds before expiry to refresh token |
| `AA_HTTP_TIMEOUT_SECONDS` | No | 30 | Request timeout |
| `AA_LOG_LEVEL` | No | WARNING | DEBUG for request tracing |

## Troubleshooting

**401 errors on startup:**
Check `AA_API_KEY` is correct and API access is enabled in Control Room settings.

**Bot not found:**
Call `list_bots` with no filter to see all available bot names, then match the exact name.

**deploy_bot returns 400:**
`run_as_user_id` must be a valid numeric user ID for the device's credential mapping. Check Control Room → Devices to find the correct runner user.

**WLM tools return permission error:**
The service account needs the `AAE_Queue Admin` role. Add it in Control Room → Roles.

**Enable debug logging:**
Set `AA_LOG_LEVEL=DEBUG` to log all request URLs and response codes to stderr.

## License

MIT
