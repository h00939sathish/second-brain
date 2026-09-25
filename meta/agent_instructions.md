# Agent Integration

This file used to hold a hand-maintained copy of the multi-agent protocol. It drifted
from the implementation, so the protocol now has exactly one source of truth:

```bash
brain bootstrap                        # print it (also written to AGENTS.md)
curl -s localhost:8000/agent/bootstrap # same text over HTTP
```

`brain setup` regenerates `AGENTS.md`, writes the `SKILL.md` that agents discover on
their own, and registers the MCP server in every agent CLI it finds on this machine, so
nothing here needs to be copied by hand. `brain doctor` tells you whether each layer is
actually in place.

## The protocol, in short

1. `brain start --agent <you> --files <paths you will write>` — leases are enforced.
2. Work. `brain post "..."` for findings other agents need now.
3. `brain claim "..." --source <path>` for anything durable you proved;
   `brain review <id>` once you have checked the source.
4. `brain end <id> --target-agent <next> --test-status "..."` — hand off explicitly.
5. Cards move `backlog → planning → running → review → done`; the move to `done`
   requires the evidence from step 4.

Roles are declared in `brain/const.py` (`AGENT_ROLES`) and are advisory except for the
review gate, which is enforced in `brain/board.py`.

## Workspaces

You are scoped to a workspace automatically, from your working directory
(`.brain-workspace`, `git config brain.workspace`, or the registered project path).
`brain whoami` tells you which one. Claims written with `--scope global` are readable
from every workspace; everything else stays inside yours.

Your brief keeps the two apart, so you never have to guess which is which:

```
## Knowledge — jarvis (5)                       <- this project's own work
## Shared truth — from `global` (19)            <- what every workspace can see
```

If a record landed in the wrong place, `brain reclassify --dry-run` shows what would
move and `brain reclassify` moves it.

## The guard hook

`brain guard` runs before an edit. It clears you when the active session is *yours* (or
the human operator's), and otherwise refuses only the paths that are actually leased by
somebody else — parallel work on different files is allowed. Pass `--files a.py,b.py`
when you call it directly; clients that pipe a JSON payload can use `--stdin-json`.
