# Installation Guide

Step-by-step setup for aa-mcp-server with Claude Code.

## Prerequisites

Check that you have the required tools before starting.

**Python 3.11 or later:**
```bash
python3 --version
```
If not installed, download from [python.org](https://python.org) or use your system package manager.

**Claude Code:**
```bash
claude --version
```
If not installed, follow the [Claude Code installation guide](https://docs.anthropic.com/en/docs/claude-code).

**Git:**
```bash
git --version
```

**Automation Anywhere access:**
- Control Room URL (e.g., `https://your-tenant.automationanywhere.digital`)
- A service account username
- An API key: Control Room > Settings > Profile > API Key
- The service account must have:
  - "Run my bots" privilege
  - Bot Runner license
  - `AAE_Queue Admin` role (for WLM queue tools only)

---

## Step 1: Clone the repository

```bash
git clone https://github.com/VankProgrammingAndDesign/aa-mcp-server.git
cd aa-mcp-server
```

---

## Step 2: Create a virtual environment

```bash
python3 -m venv .venv
```

Activate it:

**macOS / Linux:**
```bash
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

Your prompt will show `(.venv)` when the environment is active.

---

## Step 3: Install the package

```bash
pip install -e .
```

Verify the binary is available:
```bash
which aa-mcp-server
```

---

## Step 4: Configure credentials

Copy the example file:
```bash
cp .env.example .env
```

Open `.env` and fill in your values:
```
AA_CONTROL_ROOM_URL=https://your-tenant.automationanywhere.digital
AA_USERNAME=your.username@company.com
AA_API_KEY=your-40-character-api-key
```

To find your API key: log in to Control Room, go to Settings > Profile > API Key. If no key exists, click "Generate API Key".

Do not commit `.env` to version control. The repo's `.gitignore` excludes it.

> **Only need the offline analysis / UiPath-migration tools?** You can skip this step entirely — see [Setup without the Control Room API](#setup-without-the-control-room-api-offline--analysis-only) below.

---

## Step 5: Get the absolute path to the server binary

Claude Code requires the absolute path to the server executable inside your virtual environment.

**macOS / Linux:**
```bash
echo "$(pwd)/.venv/bin/aa-mcp-server"
```

**Windows (PowerShell):**
```powershell
(Get-Command aa-mcp-server).Source
```

Copy this path. Use it in Step 6.

---

## Step 6: Register with Claude Code

Registering through Claude Code is the primary path.

### Option A: Ask Claude Code (recommended)

Open a Claude Code session and paste this prompt, filling in the path (from Step 5) and your credentials:

```
Add the aa-mcp-server MCP to my Claude Code config:
- Server binary: /absolute/path/to/aa-mcp-server/.venv/bin/aa-mcp-server
- AA_CONTROL_ROOM_URL: https://your-tenant.automationanywhere.digital
- AA_USERNAME: your.username@company.com
- AA_API_KEY: your-40-character-api-key
Register it as "automation-anywhere" with --scope user.
```

Claude Code runs the `claude mcp add` command for you.

### Option B: Run `claude mcp add` yourself

Replace the path and credential placeholders with your actual values.

**macOS / Linux:**
```bash
claude mcp add --scope user automation-anywhere \
  --env AA_CONTROL_ROOM_URL=https://your-tenant.automationanywhere.digital \
  --env AA_USERNAME=your.username@company.com \
  --env AA_API_KEY=your-40-character-api-key \
  -- /absolute/path/to/aa-mcp-server/.venv/bin/aa-mcp-server
```

**Windows (PowerShell):**
```powershell
claude mcp add --scope user automation-anywhere `
  --env AA_CONTROL_ROOM_URL=https://your-tenant.automationanywhere.digital `
  --env AA_USERNAME=your.username@company.com `
  --env AA_API_KEY=your-40-character-api-key `
  -- C:\path\to\aa-mcp-server\.venv\Scripts\aa-mcp-server.exe
```

`--scope user` writes to `~/.claude.json`, making the server available in all your Claude Code projects.

For project-scoped setup (current directory only), use `--scope project`. This writes to `.mcp.json` in the current directory. Commit that file to version control to share the config with your team.

---

## Step 7: Verify the connection

Start a Claude Code session:
```bash
claude
```

Inside the session, run:
```
/mcp
```

The output shows:
```
automation-anywhere    connected
```

If the status shows `error` or the server does not appear, see Troubleshooting below.

---

## Setup without the Control Room API (offline / analysis-only)

The **Bot Package Analysis** tools (`load_bot_package`, `list_bot_actions`,
`get_bot_variables`, `get_bot_structure`, `search_bot_actions`) and the **UiPath
Migration** tools (`summarize_bot_process`, `generate_uipath_template`,
`validate_uipath_project`) work entirely on local A360 export ZIPs. They need no
Control Room connection, no network, and no valid credentials.

Just **omit** the credentials — the server starts without them. You can skip
Step 4 entirely and register with no `--env` flags in Step 6:

```bash
claude mcp add --scope user automation-anywhere \
  -- /absolute/path/to/aa-mcp-server/.venv/bin/aa-mcp-server
```

Steps 1–3 and 5–7 are otherwise identical. Only the Control Room tools
(`list_bots`, `deploy_bot`, `list_queues`, run history, etc.) need real
credentials — they return a clear "credentials not configured" error until
`AA_CONTROL_ROOM_URL`, `AA_USERNAME`, and `AA_API_KEY` are set.

---

## Troubleshooting

**`aa-mcp-server: command not found` after `pip install -e .`**
The virtual environment is not active. Run `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\Activate.ps1` (Windows), then retry.

**`/mcp` shows `error` status**
Run the server directly to see startup output:
```bash
AA_LOG_LEVEL=DEBUG aa-mcp-server
```
Common causes of a startup `error`: the wrong binary path or command, or the virtual environment not active. Credential, URL, and network problems do **not** surface here — the `AA_*` credentials are optional at startup and the Control Room is only contacted on a tool call (see below).

**`authentication failed` when a Control Room tool is called**
Authentication is lazy: the server connects to the Control Room only when a Control Room tool runs, not at startup. If a tool returns an auth error, `AA_API_KEY` is the 40-character key from Control Room > Settings > Profile > API Key. Your login password won't work here. Regenerate the key if needed. (The analysis and UiPath-migration tools never authenticate, so they work without any credentials.)

**SSL certificate errors**
Add `--env AA_SSL_VERIFY=false` to your `claude mcp add` command. See [FAQ.md](FAQ.md) for details.

**Wrong path in config**
Check the registered command:
```bash
claude mcp list
```
Remove and re-add if the path is wrong:
```bash
claude mcp remove automation-anywhere
# then re-run the claude mcp add command from Step 6
```

**Windows: execution policy error when activating the virtual environment**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Then retry activating the virtual environment.
