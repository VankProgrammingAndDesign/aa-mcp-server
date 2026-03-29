# Claude Code Installation Guide

Everything you need to connect aa-mcp-server to Claude Code in one place. No other files needed.

## Prerequisites

- Python 3.11+ (`python3 --version`)
- Claude Code installed (`claude --version`)
- Git (`git --version`)
- Your Automation Anywhere Control Room URL, service account username, and API key
  - API key location: Control Room > Settings > Profile > API Key

---

## 1. Clone and install

```bash
git clone https://github.com/VankProgrammingAndDesign/aa-mcp-server.git
cd aa-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/VankProgrammingAndDesign/aa-mcp-server.git
cd aa-mcp-server
python3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

---

## 2. Get the absolute path to the binary

Use this path in Step 3.

**macOS / Linux:**
```bash
echo "$(pwd)/.venv/bin/aa-mcp-server"
```

**Windows (PowerShell):**
```powershell
(Get-Command aa-mcp-server).Source
```

Copy the output.

---

## 3. Register with Claude Code

### Option A: Ask Claude Code to do it

Open a Claude Code session and paste this prompt, filling in your values:

```
Add the aa-mcp-server MCP to my Claude Code config. Use these details:
- Server binary: /absolute/path/to/aa-mcp-server/.venv/bin/aa-mcp-server
- AA_CONTROL_ROOM_URL: https://your-tenant.automationanywhere.digital
- AA_USERNAME: your.username@company.com
- AA_API_KEY: your-40-character-api-key

Register it as "automation-anywhere" with --scope user.
```

Claude Code will run the `claude mcp add` command for you.

### Option B: Run it yourself

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

`--scope user` makes the server available in all your Claude Code projects. Use `--scope project` to limit it to the current directory.

---

## 4. Verify

```bash
claude
```

Inside the session:
```
/mcp
```

The output shows:
```
automation-anywhere    connected
```

---

## Quick fixes

**`aa-mcp-server: command not found`**
Virtual environment is not active. Run `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\Activate.ps1` (Windows), then retry `pip install -e .`.

**`/mcp` shows `error`**
Run the server directly to see what failed:
```bash
AA_LOG_LEVEL=DEBUG aa-mcp-server
```

**`authentication failed`**
`AA_API_KEY` is the 40-character key from Control Room > Profile > API Key. Your login password won't work here.

**Self-signed SSL certificate**
Add `--env AA_SSL_VERIFY=false` to the `claude mcp add` command above.

**Wrong path registered**
```bash
claude mcp remove automation-anywhere
```
Then re-run Step 3.

**Windows: execution policy error**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Updating

```bash
cd /path/to/aa-mcp-server
git pull
source .venv/bin/activate
pip install -e .
```

Your Claude Code config stays the same.

---

## Removing

```bash
claude mcp remove automation-anywhere
```
