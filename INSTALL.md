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

Run `claude mcp add` with your credentials. Replace the path and credential placeholders with your actual values.

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

## Troubleshooting

**`aa-mcp-server: command not found` after `pip install -e .`**
The virtual environment is not active. Run `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\Activate.ps1` (Windows), then retry.

**`/mcp` shows `error` status**
Run the server directly to see startup output:
```bash
AA_LOG_LEVEL=DEBUG aa-mcp-server
```
Common causes: wrong `AA_CONTROL_ROOM_URL` (check for a trailing slash), invalid API key, or no network path to Control Room.

**`authentication failed` on startup**
`AA_API_KEY` is the 40-character key from Control Room > Settings > Profile > API Key. Your login password won't work here. Regenerate the key if needed.

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
