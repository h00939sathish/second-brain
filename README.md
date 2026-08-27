# Second Brain — Multi-Agent Coordination Hub

Shared brain for all coding agents (Hermes, opencode, Claude Code, Codex,
Antigravity, etc.). Two layers:

**Knowledge** — long-term facts with truth lifecycle:
- `claims/` — one file per claim: `YYYYMMDD-cid.md`
- status lifecycle: active → superseded / expired / disputed
- recall withholds non-current truth and says why

**Coordination** — multi-agent awareness:
- `sessions/` — agent presence + progress (`s-YYYYMMDD-*.md`)
- `context/` — shared discoveries/decisions (`ctx-YYYYMMDD-*.md`)

Git = audit trail. Engine: `python engine.py <cmd>`

## MCP Integration

`mcp/brain_mcp.py` exposes the engine as an MCP server (stdio):

**Knowledge tools:** `brain_status`, `brain_recall`, `brain_claim`,
`brain_supersede`, `brain_dispute`, `brain_verify`, `brain_related`,
`brain_sweep`

**Coordination tools:** `brain_session_start`, `brain_session_update`,
`brain_session_end`, `brain_sessions`, `brain_post`, `brain_read`,
`brain_dashboard`

### Registering with agents

**opencode** (`~/.config/opencode/opencode.json`):
```json
{ "mcp": { "second-brain": {
    "command": "python", "args": ["mcp/brain_mcp.py"],
    "cwd": "D:\\projects\\second-brain"
}}}
```

**Hermes** (`~/.hermes/config.yaml`):
```yaml
mcp_servers:
  second_brain:
    command: python
    args: ["mcp/brain_mcp.py"]
    cwd: D:\projects\second-brain
```

**Claude Code** (`.claude/mcp.json` or `claude_desktop_config.json`):
```json
{ "mcpServers": { "second-brain": {
    "command": "python", "args": ["mcp/brain_mcp.py"],
    "cwd": "D:\\projects\\second-brain"
}}}
```

**Antigravity**: configure via MCP settings in the IDE.

MCP venv: `mcp/.venv` (python 3.11, `mcp<2`). Recreate:
`uv venv --python 3.11 .venv && uv pip install --python .venv "mcp<2"`

## L0 Pointers

`meta/l0_pointers.md` is auto-rebuilt by `sweep`. It contains:
1. Active sessions (who's doing what)
2. Recent context notes
3. Active claims (truncated to fit 2.2KB budget)

Inject into every agent session via `instructions` config.

Vault: D:\projects\second-brain
