# Second Brain (Hermes L1 vault)

Provenance-first tiered memory. L0 = Hermes memory tool pointers,
L1 = this vault (claims + evidence), L2 = Hermes session transcripts (opaque).

- claims/: one file per claim: `YYYYMMDD-cid.md`
- truth lifecycle: status in (active, superseded, expired, disputed)
- recall withholds expired/superseded/disputed and says why (see `recall`)
- git = audit trail. Engine: `python engine.py <cmd>`

## Shared across agents (MCP)

`mcp/brain_mcp.py` exposes the engine as an MCP server (stdio), so opencode,
Hermes, Claude Code, etc. all read/write the same truth store:

- tools: `brain_status`, `brain_recall`, `brain_claim`, `brain_supersede`,
  `brain_dispute`, `brain_verify`, `brain_related`, `brain_sweep`
- registered in opencode (`~/.config/opencode/opencode.json` -> mcp.second-brain)
  and Hermes (`~/.hermes/config.yaml` -> mcp_servers.second_brain)
- its venv: `mcp/.venv` (python 3.11, `mcp<2`). Recreate:
  `uv venv --python 3.11 .venv && uv pip install --python .venv "mcp<2"`
- L0 pointer set (`meta/l0_pointers.md`, rebuilt by `sweep`) is injected into
  every opencode session via `instructions`.

Vault: D:\projects\second-brain
