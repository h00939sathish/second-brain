# CLAUDE.md

Claude Code: read **`AGENTS.md`** in this directory first — it is the tool-agnostic
protocol, and it is also served at `http://127.0.0.1:8000/agent/bootstrap` and printed
by `brain bootstrap`.

## Non-negotiables

1. `brain start --agent claude` before your first write. Add `--files a.py,b.py` for
   anything you will modify: those become refusals for any other agent.
2. Do not edit vault markdown by hand. Use `brain` so the record is validated,
   indexed and committed correctly.
3. `brain end <session-id> --summary ... --test-status ...` before you finish. A card
   cannot reach `done` without that evidence.
4. Durable fact → `brain claim "<text>" --source <path>`. Verified it → `brain review <id>`.

A `PreToolUse` hook (installed by `brain setup`) runs `brain guard --stdin-json` before
every edit. It reads the file path out of the hook payload and refuses when you have no
session of your own, or when the file you are about to touch is leased by another live
agent. `BRAIN_BYPASS=1` is the documented break-glass path.

The same `brain setup` writes a `SKILL.md` into `~/.agents/skills/second-brain/` (and
into each bound project's `.agents/skills/`), so Claude Code discovers the brain on its
own with no configuration.

## Where things live

```bash
brain whoami        # your agent, role, workspace, session
brain brief         # your workspace context: leases, board, notes, top claims
brain recall "..."  # knowledge from other agents (BM25, scoped)
brain repair --help # recovery tools
```

Vault: `/mnt/shared/projects/second-brain`. Layout and design notes: `README.md`.
Python API: the `brain/` package, one module per concern — `knowledge.py` (claims),
`board.py` (tasks/specs), `coordination.py` (sessions/leases), `agents.py` (setup).

## Working on the brain itself

```bash
python3 -m unittest discover -s tests -t .   # must stay green
npm run lint && npm run build                 # dashboard
python3 engine.py doctor                      # end-to-end self check
```

The test suite runs against a throwaway vault in `/tmp`; it never touches this one.
If you add a behaviour to a rule, add the test that proves it is enforced.
