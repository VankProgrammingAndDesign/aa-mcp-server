# Frequently Asked Questions

## Automation Anywhere compatibility

**Which versions of Automation Anywhere does this support?**
This server targets Automation Anywhere 360 (A360), both cloud-hosted and on-premises deployments. It uses the v2 and v3 Control Room REST APIs. A2019 is not supported.

**Does this work with Community Edition?**
Community Edition includes Control Room but may have API rate limits or restricted features. The core bot tools (`list_bots`, `list_devices`, `deploy_bot`, `list_running_automations`, `list_run_history`) work on Community Edition. The WLM tools (`list_queues`, `get_queue_detail`) require a licensed queue configuration.

**Does this work with on-premises deployments?**
Yes. Set `AA_CONTROL_ROOM_URL` to your on-premises Control Room URL. If your server uses a self-signed SSL certificate, set `AA_SSL_VERIFY=false`.

---

## Credentials and permissions

**Where do I find my API key?**
Log in to Control Room. Go to Settings (gear icon) > Profile > API Key. If the field is empty, click "Generate API Key" and copy the full 40-character key.

**What permissions does the service account need?**
Minimum for bot tools:
- "Run my bots" privilege
- Bot Runner license assigned to the account

For WLM queue tools:
- `AAE_Queue Admin` role (assigned in Control Room > Roles)

**Can I use my personal Control Room account?**
You can. A dedicated service account is safer. Personal accounts are subject to password expiration, MFA prompts, and audit trail implications when bots run under your identity.

**Does this server store my credentials?**
No. Credentials are read from environment variables at startup. The server holds the JWT token in memory and discards it when the process exits.

---

## SSL and network

**My Control Room uses a self-signed certificate. How do I connect?**
Set `AA_SSL_VERIFY=false` in your `.env` file:
```
AA_SSL_VERIFY=false
```
Or pass it in the `claude mcp add` command:
```bash
claude mcp add --scope user automation-anywhere \
  --env AA_SSL_VERIFY=false \
  --env AA_CONTROL_ROOM_URL=https://your-cr.internal \
  --env AA_USERNAME=your.username@company.com \
  --env AA_API_KEY=your-api-key \
  -- /path/to/.venv/bin/aa-mcp-server
```
Disabling SSL verification removes certificate validation. Use it only on internal networks where you control the server.

**The server times out connecting to Control Room.**
Increase the timeout:
```
AA_HTTP_TIMEOUT_SECONDS=60
```
If the problem continues, confirm that the machine running Claude Code can reach your Control Room URL:
```bash
curl -I https://your-tenant.automationanywhere.digital/v3/usermanagement/users/token
```

**I have multiple Control Room tenants. Can I connect to more than one?**
Yes. Register each as a separate MCP server with a different name:
```bash
claude mcp add --scope user aa-production \
  --env AA_CONTROL_ROOM_URL=https://prod.automationanywhere.digital \
  --env AA_USERNAME=svc-account@company.com \
  --env AA_API_KEY=prod-api-key \
  -- /path/to/.venv/bin/aa-mcp-server

claude mcp add --scope user aa-staging \
  --env AA_CONTROL_ROOM_URL=https://staging.automationanywhere.digital \
  --env AA_USERNAME=svc-account@company.com \
  --env AA_API_KEY=staging-api-key \
  -- /path/to/.venv/bin/aa-mcp-server
```
Both appear in `/mcp`. Specify which environment you want in your request and Claude will use it.

---

## Bot operations

**What happens if the bot fails during a run?**
`deploy_bot` returns a deployment ID at the moment the bot is queued. It does not wait for completion. To check the outcome, call `list_run_history` with the bot name after the run finishes. Returned status values include `COMPLETED`, `FAILED`, `STOPPED`, and `TIMED_OUT`.

**Can I pass input variables to a bot?**
The current version of `deploy_bot` does not support runtime input variables. For bots that require inputs, set variable defaults in Control Room > Bots > Variables before deploying through this server. Input variable support is planned for a future release.

**The bot I want does not appear in `list_bots`.**
The service account needs access to the folder containing the bot. In Control Room, go to Bots > Folder Permissions and verify the service account has "Run" access to the relevant folder.

**What is `run_as_user_id` and where do I find it?**
When deploying a bot, Control Room requires a credential mapping that specifies which local Windows user the bot runner logs in as. `run_as_user_id` is the numeric ID for that user in Control Room. Find it in Control Room > Devices > [device name] > Credentials. Passing the wrong value causes a 400 error from `deploy_bot`.

---

## Bot package analysis

**What is bot package analysis?**
The `load_bot_package`, `list_bot_actions`, `get_bot_variables`, `get_bot_structure`, and `search_bot_actions` tools parse A360 bot export ZIP files stored on your local machine. They require no Control Room connection and work without any API credentials.

**Which file format do these tools accept?**
A360 export ZIPs exported from Control Room. To export: open Control Room, go to Bots, select the bots or folders you want, and use Export. The ZIP contains bot definition files, screenshots, and JAR packages.

**Do these tools work with Community Edition?**
Yes. The export format is the same across Community Edition, cloud-hosted, and on-premises A360 deployments.

**How do I use these tools?**
Call `load_bot_package` first with the absolute path to the ZIP file. It returns the bot names found in the package. Pass those names to `list_bot_actions`, `get_bot_variables`, or `get_bot_structure` for deeper analysis. Use `search_bot_actions` to find all actions of a specific type across every bot in the package.

**What packages does the parser support?**
The parser reads all standard A360 packages. It handles nested actions (If, Loop, Step bodies), error handler catch blocks (ErrorHandler branches), subtask references (TaskBot/runTask), and all variable types. Recorder capture attributes are included in `get_bot_structure` output.

**Does the parser modify the ZIP file?**
No. All tools are read-only.

---

## Authentication

**How often does the JWT token refresh?**
The server checks token expiry on every request and refreshes when fewer than `AA_TOKEN_REFRESH_BUFFER_SECONDS` remain (default: 60 seconds). Refreshes happen in the background and do not delay tool calls.

**My API key stopped working after a password change.**
A password change on the Control Room account can invalidate the API key. Regenerate it in Control Room > Settings > Profile > API Key, then update `AA_API_KEY` in your configuration.

---

## Claude Code integration

**Can I run this without a Control Room (analysis / UiPath migration only)?**
Yes. The bot-package-analysis tools (`load_bot_package`, `list_bot_actions`, `get_bot_variables`, `get_bot_structure`, `search_bot_actions`) and the UiPath-migration tools (`summarize_bot_process`, `generate_uipath_template`, `validate_uipath_project`) work entirely on local export ZIPs with no Control Room connection or credentials. Just omit the credentials — the server starts without them:
```bash
claude mcp add --scope user automation-anywhere \
  -- /path/to/.venv/bin/aa-mcp-server
```
The Control Room tools return a clear "credentials not configured" error until `AA_CONTROL_ROOM_URL`, `AA_USERNAME`, and `AA_API_KEY` are set; the analysis and migration tools work regardless.

**What is the difference between user-level and project-level MCP config?**
- User-level (`--scope user`): writes to `~/.claude.json`. The server is available in all Claude Code sessions on your machine.
- Project-level (`--scope project`): writes to `.mcp.json` in the current directory. The server is available only when Claude Code opens that directory. Useful when different projects connect to different Control Rooms.

**How do I remove the server?**
```bash
claude mcp remove automation-anywhere
```

**How do I update to a newer version?**
```bash
cd /path/to/aa-mcp-server
git pull
source .venv/bin/activate
pip install -e .
```
Your Claude Code config stays the same unless the binary path changed.

**Can I use this with Claude Desktop instead of Claude Code?**
Claude Desktop uses a different config file (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS). Add the server block to the `mcpServers` section of that file using the same JSON structure shown in the README manual configuration section. This server is built and tested for Claude Code.
