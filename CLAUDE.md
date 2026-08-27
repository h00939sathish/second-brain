# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Highlights
This is a "second brain" tiered memory system (Hermes L1 vault). There are deterministic operations built in `engine.py` using Python, backed by local Markdown files.

- **L0 Memory**: Small footprint, represented as pointers (in `meta/l0_pointers.md`). Budget is constrained (~2.2KB). This tier is injected into tools/sessions.
- **L1 Memory (The Vault)**: Granular claims stored in `claims/` as markdown files (`YYYYMMDD-cid.md`). Files have a specific lifecycle: `active`, `superseded`, `expired`, or `disputed`. Includes YAML frontmatter for tags and status.
- **L2 Memory**: Opaque session transcripts located in `sessions/` (ignored from Git). Handled by Hermes session search.
- No LLMs are invoked deterministically in the engine for recall/sweep processes. 
- FastMCP tool `mcp/brain_mcp.py` exposes this internal system globally via stdio to tools like Claude Code and opencode. 

## Key Commands

### Using the Engine
The engine manages the memory data and can be operated directly using `python engine.py <cmd>`. Below are common operations:

- **Check System Status**: Show counts by status, L0 memory budget estimation, and perform chain integrity checks.
  ```bash
  python engine.py status
  ```
- **Add a Claim**:
  ```bash
  python engine.py claim "Your concise claim text" --status active --confidence 0.9 --source tool --tags tag1,tag2
  ```
  *(Status must be one of: `active`, `superseded`, `expired`, `disputed`)*
- **Dispute a Claim**: Keeps the evidence but marks it as disputed.
  ```bash
  python engine.py dispute <claim_id> --reason "Why it is disputed" [--by <who>]
  ```
- **Recall Search**: Deterministic recall for claims. (withheld items are omitted by default)
  ```bash
  python engine.py recall <query> [--tag <tag>] [--status <status>] [--all]
  ```
- **Sweep Maintenance Tasks**: Rebuilds L0 pointers, expires stale items, and optionally auto-commits if `commit=True` is provided.
  ```bash
  python engine.py sweep [--commit]
  ```

### Managing the MCP Server
- The FastMCP server configuration runs isolated on it's own Python 3.11 virtual environment located at `mcp/.venv`. 
- To reinstall the dependencies:
  ```bash
  uv venv --python 3.11 .venv && uv pip install --python .venv "mcp<2"
  ```
- The FastMCP server relies on executing the `mcp/brain_mcp.py` script. The server starts with internal transport using `stdio`.
  ```bash
  mcp/.venv/Scripts/python.exe mcp/brain_mcp.py
  ```

### Testing
- There are no typical unit testing tools currently setup (like PyTest or Unittest) and there is no tests directory.
- Test implementations by running direct commands mapped to `engine.py` methods and checking how the claims format inside of `claims/` outputs change in Bash shell. (Note: The engine features atomic writes using `*.tmp` + rename steps).