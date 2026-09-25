# Second Brain — agent integration

Shared memory + task board + coordination for every coding agent on this machine.
Vault: `/mnt/shared/projects/second-brain`  |  Generated 2026-09-24T12:14:04Z by `brain setup`; do not edit by hand.

## If you are reading this you are already connected

There is nothing to configure. One of these brought you here:

* the `second-brain` **skill** in `.agents/skills/` or `~/.agents/skills/` — your client
  discovered it on its own
* the **MCP** server `second-brain`
* the `brain` command on `PATH`
* this file, because it was pasted in

## Zero-config access

```bash
brain status                      # health, board, leases, L0 budget
brain whoami                      # your agent + workspace, as the brain sees it
brain start --agent <you> --task "what you are doing" --files a.py,b.py
brain post "note for other agents"      # scratchpad, visible to everyone
brain recall "how does auth work"       # knowledge written by other agents
brain end <session-id> --summary "..." --test-status "pytest: 12 passed"
```

If `brain` is not on PATH, call the engine directly:
`python3 /mnt/shared/projects/second-brain/engine.py <command>`.

## The protocol (5 lines, enforced not suggested)

1. `brain start` when you begin. Pass `--files` for anything you will write; conflicting
   leases are **refused**, so this is how agents avoid clobbering each other.
2. Work. `brain post` findings you want visible to the other agents right now.
3. `brain claim "..."` for anything durable you proved (with `--source`). Claims are the
   knowledge base; other agents recall them later.
4. `brain end <id> --target-agent <next> --test-status "..."` — hand off explicitly.
5. Task cards move `backlog -> planning -> running -> review -> done`. The move to
   `done` is **refused** without a finished session that recorded tests or a handoff.

A write with no session of your own is blocked by the `brain guard` hook. Clearance is
per-agent: another agent's session does not authorise your edits, and you are only
refused on paths that agent actually leased.

## Workspaces

Work is auto-scoped: the workspace is detected from your cwd (a `.brain-workspace`
marker or `git config brain.workspace`), so what you write about JARVIS stays in the
JARVIS workspace. Claims written with `--global` are shared with every workspace.
Your brief prints them as two labelled sections. Detected workspace: `auto-detected from your cwd`.

## MCP (if your agent supports it)

`brain setup` writes the server entry into Claude, Codex, opencode, Gemini/Antigravity
and Crush configs automatically, and installs the skill everywhere it is discovered.
The server is `second-brain` and is started with:

```
"/mnt/shared/projects/second-brain/mcp/brain_mcp.py"
```

`brain doctor` verifies all of the above end to end.
