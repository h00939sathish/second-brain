# -*- coding: utf-8 -*-
"""Agent discovery and self-configuration.

The goal: bringing a new agent to the brain should require no per-agent hand-editing.
Three layers, cheapest first, so any agent that can run a shell command is reachable:

  1. `brain` on PATH — works for every agent, no config file at all
  2. native MCP registration — written automatically into whatever config file each
     installed agent actually reads (Claude, Codex, opencode, Gemini/Antigravity, Crush)
  3. `AGENTS.md` + `brain bootstrap` — a paste-in brief for anything else, including
     hosted or closed agents (Freebuff, cloud IDEs) that cannot read local config

Every writer is idempotent, backs the file up first, preserves its mode, and only
touches the keys it owns.
"""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from . import const, workspaces as ws_mod
from .paths import (USER_CONFIG, VAULT, atomic_write, now, read_json, read_text, write_json)

HOME = Path.home()
BACKUP_SUFFIX = ".brainbak"


# ---- discovery -----------------------------------------------------------


def find_cli(agent: str):
    """Absolute path of an agent CLI, or None. Tries PATH, then ~/.local/bin."""
    spec = const.AGENT_CLIS.get(agent)
    if not spec:
        return None
    candidates = list(spec["bins"])
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    for name in candidates:
        for directory in (HOME / ".local" / "bin", HOME / "bin", HOME / ".cargo" / "bin"):
            candidate = directory / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def installed(agent: str) -> bool:
    return find_cli(agent) is not None


def detect_agents() -> dict:
    return {name: find_cli(name) for name in const.AGENT_CLIS}


def python_for_mcp() -> str:
    """Prefer the MCP venv interpreter (it has the `mcp` package), else python3."""
    venv = VAULT / "mcp" / ".venv"
    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.exists():
            return str(candidate)
    return shutil.which("python3") or shutil.which("python") or "python3"


def mcp_server_entry() -> dict:
    return {
        "command": python_for_mcp(),
        "args": [str(VAULT / "mcp" / "brain_mcp.py")],
        "env": {"SECOND_BRAIN_VAULT": str(VAULT)},
        "description": "Second Brain — shared memory, task board and agent coordination.",
    }


# ---- file helpers --------------------------------------------------------


def _backup(path: Path) -> str:
    if not path.exists():
        return ""
    target = path.with_name(path.name + f"{BACKUP_SUFFIX}-{now().replace(':', '')}")
    shutil.copy2(path, target)
    return str(target)


def _write_preserving_mode(path: Path, text: str) -> None:
    mode = None
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    atomic_write(path, text)
    if mode is not None:
        os.chmod(path, mode)


def _load_json(path: Path) -> dict:
    data = read_json(path, None)
    if data is None:
        if path.exists():
            raise ValueError(f"{path} exists but is not valid JSON; fix it or move it aside")
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _save_json_if_changed(path: Path, data: dict, actions: list, label: str) -> None:
    existing = read_text(path) if path.exists() else ""
    rendered = json.dumps(data, indent=2) + "\n"
    if existing.strip() == rendered.strip():
        actions.append(f"{label}: already configured")
        return
    backup = _backup(path)
    _write_preserving_mode(path, rendered)
    actions.append(f"{label}: updated" + (f" (backup {Path(backup).name})" if backup else ""))


# ---- per-agent writers ---------------------------------------------------


def configure_claude(actions: list, dry_run: bool = False) -> None:
    config = HOME / ".claude.json"
    data = _load_json(config)
    servers = data.setdefault("mcpServers", {})
    entry = mcp_server_entry()
    wanted = {"command": entry["command"], "args": entry["args"], "env": entry["env"],
              "description": entry["description"]}
    if servers.get("second-brain") == wanted:
        actions.append("claude (MCP): already configured")
    elif dry_run:
        actions.append(f"claude (MCP): would register second-brain in {config}")
    else:
        servers["second-brain"] = wanted
        _save_json_if_changed(config, data, actions, "claude (MCP)")

    settings = HOME / ".claude" / "settings.json"
    if settings.exists():
        try:
            hooks_data = _load_json(settings)
        except ValueError:
            actions.append("claude (hook): settings.json unreadable, skipped")
            return
        command = guard_command("claude")
        pre = hooks_data.setdefault("hooks", {}).setdefault("PreToolUse", [])
        matcher = "Edit|Write|MultiEdit|NotebookEdit"

        def is_ours(entry) -> bool:
            """Recognise hooks we wrote earlier, including the previous command format.

            Matching on the shim path rather than the exact string means an upgrade that
            changes the arguments replaces the old hook instead of stacking a second one
            on the same matcher (which would run the guard twice).
            """
            return entry.get("matcher") == matcher and any(
                "guard" in str(h.get("command", "")) and "brain" in str(h.get("command", ""))
                for h in entry.get("hooks", [])
            )

        if any(is_ours(e) and all(h.get("command") == command for h in e.get("hooks", []))
               for e in pre):
            actions.append("claude (hook): already configured")
        elif dry_run:
            actions.append("claude (hook): would add a PreToolUse guard")
        else:
            hooks_data["hooks"]["PreToolUse"] = [e for e in pre if not is_ours(e)]
            hooks_data["hooks"]["PreToolUse"].append(
                {"matcher": matcher,
                 "hooks": [{"type": "command", "command": command}]})
            _save_json_if_changed(settings, hooks_data, actions, "claude (hook)")


def configure_codex(actions: list, dry_run: bool = False) -> None:
    config = HOME / ".codex" / "config.toml"
    node = find_cli("codex")
    entry = mcp_server_entry()
    block = (
        "\n[mcp_servers.second-brain]\n"
        "enabled = true\n"
        f'command = "{entry["command"]}"\n'
        f'args = [ "{entry["args"][0]}" ]\n'
        f'cwd = "{VAULT}"\n'
        "\n[mcp_servers.second-brain.env]\n"
        f'SECOND_BRAIN_VAULT = "{VAULT}"\n'
    )
    if node is None:
        actions.append("codex (MCP): CLI not installed, skipped")
        return
    if dry_run:
        actions.append(f"codex (MCP): would write [mcp_servers.second-brain] into {config}")
        return
    existing = read_text(config) if config.exists() else ""
    # Section-level surgery, line by line. A regex that stops at the next `[` leaves
    # `[mcp_servers.second-brain.env]` behind, which silently produces a duplicate table
    # (and a TOML error) on the second run.
    prefix = "[mcp_servers.second-brain"
    kept, skipping = [], False
    for line in existing.split("\n"):
        if line.startswith(prefix):
            skipping = True
            continue
        if skipping and line.startswith("["):
            skipping = False
        if not skipping:
            kept.append(line)
    stripped = "\n".join(kept).rstrip("\n")
    updated = (stripped + "\n" + block) if stripped else block.lstrip("\n")
    if updated.strip() == existing.strip():
        actions.append("codex (MCP): already configured")
        return
    backup = _backup(config)
    _write_preserving_mode(config, updated)
    actions.append("codex (MCP): updated" + (f" (backup {Path(backup).name})" if backup else ""))


def configure_opencode(actions: list, dry_run: bool = False) -> None:
    config = HOME / ".config" / "opencode" / "opencode.json"
    if not config.exists() and not (HOME / ".config" / "opencode").is_dir():
        actions.append("opencode (MCP): not installed, skipped")
        return
    data = _load_json(config) if config.exists() else {"$schema": "https://opencode.ai/config.json"}
    data.setdefault("mcp", {})["second-brain"] = {
        "type": "local",
        "command": [mcp_server_entry()["command"], mcp_server_entry()["args"][0]],
        "enabled": True,
    }
    # Rewrite any stale pointer to this vault's own instruction files, so a move of the
    # vault (or a Windows-era path) heals on the next `brain setup` instead of lingering.
    owned = {("AGENTS.md",): str(VAULT / "AGENTS.md"),
             (const.L0_NAME,): str(VAULT / "meta" / const.L0_NAME),
             ("agent_instructions.md",): str(VAULT / "meta" / "agent_instructions.md")}
    instructions, seen = [], set()
    for entry in data.get("instructions", []) or []:
        name = Path(str(entry)).name
        for names, canonical in owned.items():
            if name in names:
                entry = canonical
                break
        if entry not in seen:
            seen.add(entry)
            instructions.append(entry)
    for canonical in owned.values():
        if canonical not in seen:
            instructions.append(canonical)
    data["instructions"] = instructions
    if dry_run:
        actions.append(f"opencode (MCP): would register second-brain in {config}")
        return
    _save_json_if_changed(config, data, actions, "opencode (MCP)")
    install_plugin(actions, dry_run=dry_run)


def install_plugin(actions: list, dry_run: bool = False) -> None:
    """Install the enforcement plugin that runs `brain guard` before every edit.

    Generated from here so the plugin can never lag behind the CLI it calls.
    """
    plugin_dir = HOME / ".config" / "opencode" / "plugin"
    if not (HOME / ".config" / "opencode").is_dir():
        actions.append("guard plugin: opencode not installed, skipped")
        return
    target = plugin_dir / "brain-guard.js"
    body = OPENCODE_PLUGIN
    if target.exists() and read_text(target) == body:
        actions.append("guard plugin: up to date")
        return
    if dry_run:
        actions.append(f"guard plugin: would write {target}")
        return
    plugin_dir.mkdir(parents=True, exist_ok=True)
    _backup(target)
    _write_preserving_mode(target, body)
    actions.append(f"guard plugin: installed at {target}")


def configure_gemini(actions: list, dry_run: bool = False) -> None:
    config = HOME / ".gemini" / "config" / "mcp_config.json"
    if not config.exists() and not (HOME / ".gemini").is_dir():
        actions.append("gemini/agy (MCP): not installed, skipped")
        return
    data = _load_json(config) if config.exists() else {}
    entry = mcp_server_entry()
    data.setdefault("mcpServers", {})["second-brain"] = {
        "command": entry["command"],
        "args": entry["args"],
        "env": entry["env"],
    }
    if dry_run:
        actions.append(f"gemini/agy (MCP): would register second-brain in {config}")
        return
    _save_json_if_changed(config, data, actions, "gemini/agy (MCP)")


def configure_crush(actions: list, dry_run: bool = False) -> None:
    config = HOME / ".config" / "crush" / "crush.json"
    if not installed("crush") and not config.exists():
        actions.append("crush (MCP): not installed, skipped")
        return
    data = _load_json(config) if config.exists() else {}
    entry = mcp_server_entry()
    data.setdefault("mcp", {})["second-brain"] = {
        "type": "stdio",
        "command": entry["command"],
        "args": entry["args"],
        "env": entry["env"],
    }
    if dry_run:
        actions.append(f"crush (MCP): would register second-brain in {config}")
        return
    _save_json_if_changed(config, data, actions, "crush (MCP)")


def configure_repo(actions: list, dry_run: bool = False) -> None:
    """Vault-local pointers plus the global skill, read by every agent."""
    install_skill(actions, dry_run=dry_run)
    mcp_json = VAULT / ".mcp.json"
    data = _load_json(mcp_json)
    entry = mcp_server_entry()
    data.setdefault("mcpServers", {})["second-brain"] = {
        "command": entry["command"], "args": entry["args"], "env": entry["env"],
    }
    if dry_run:
        actions.append(f"repo .mcp.json: would register second-brain in {mcp_json}")
    else:
        _save_json_if_changed(mcp_json, data, actions, "repo .mcp.json")

    agents_md = VAULT / "AGENTS.md"
    content = bootstrap_brief()
    if agents_md.exists() and read_text(agents_md).strip() == content.strip():
        actions.append("AGENTS.md: up to date")
    elif dry_run:
        actions.append("AGENTS.md: would regenerate")
    else:
        _write_preserving_mode(agents_md, content)
        actions.append("AGENTS.md: written")


def configure_projects(actions: list, dry_run: bool = False) -> None:
    """Wire every registered project, not just this one.

    Bringing the brain to a project used to mean re-running `workspaces bind` per
    directory, which is exactly the per-project chore this is supposed to remove. One
    `brain setup` now walks the registry and installs the pointer and the skill in each
    bound project, so a project added months ago is brought up to date too.
    """
    seen = set()
    for slug in ws_mod.all_slugs():
        if slug == const.GLOBAL_WORKSPACE:
            continue
        raw = str(ws_mod.entry(slug).get("path") or "")
        if not raw:
            continue
        root = Path(raw).expanduser()
        if str(root) in seen or not root.is_dir():
            continue
        seen.add(str(root))
        if root.resolve() == Path(VAULT).resolve():
            # The vault's own AGENTS.md *is* the generated brief (see configure_repo),
            # so appending a pointer to it would duplicate the whole document.
            continue
        actions.append(f"project '{slug}': {root}")
        actions.extend(ws_mod.add_pointer(slug, str(root), dry_run=dry_run))


CONFIGURERS = {
    "claude": configure_claude,
    "codex": configure_codex,
    "opencode": configure_opencode,
    "gemini": configure_gemini,
    "agy": configure_gemini,
    "crush": configure_crush,
}


def configure(targets=None, dry_run: bool = False) -> list:
    """Configure every detected agent (or an explicit list). Returns action lines."""
    actions = []
    names = list(targets) if targets else [n for n in CONFIGURERS if installed(n)]
    if not names:
        actions.append("no agent CLIs detected on PATH")
    done_names, done_writers = set(), set()
    for name in names:
        canonical = const.AGENT_ALIASES.get(name.lower(), name.lower())
        writer = CONFIGURERS.get(canonical) or CONFIGURERS.get(name.lower())
        if canonical in done_names:
            continue
        # Two CLIs can share one config file (`gemini` and the Antigravity `agy` both
        # read ~/.gemini). Running the same writer twice would report the work twice and
        # double-back up the file.
        if writer is not None and writer in done_writers:
            done_names.add(canonical)
            continue
        done_names.add(canonical)
        if not writer:
            actions.append(f"{name}: no configurator (use `brain bootstrap` for a paste-in brief)")
            continue
        done_writers.add(writer)
        try:
            writer(actions, dry_run=dry_run)
        except (OSError, ValueError) as exc:
            actions.append(f"{name}: FAILED ({exc})")
    try:
        configure_repo(actions, dry_run=dry_run)
    except (OSError, ValueError) as exc:
        actions.append(f"repo config: FAILED ({exc})")
    return actions


# ---- the PATH shim ------------------------------------------------------


def shim_path() -> Path:
    return HOME / ".local" / "bin" / ("brain.cmd" if os.name == "nt" else "brain")


def shim_body() -> str:
    engine = VAULT / "engine.py"
    if os.name == "nt":
        return (
            "@echo off\r\n"
            f'set SECOND_BRAIN_VAULT={VAULT}\r\n'
            f'python "{engine}" %*\r\n'
        )
    return (
        "#!/bin/sh\n"
        "# Second Brain shim. Any agent that can run a shell command can use the brain.\n"
        f'export SECOND_BRAIN_VAULT="${{SECOND_BRAIN_VAULT:-{VAULT}}}"\n'
        f'exec "{shutil.which("python3") or "python3"}" "{engine}" "$@"\n'
    )


def install_shim(dry_run: bool = False) -> list:
    target = shim_path()
    body = shim_body()
    if target.exists() and read_text(target) == body:
        return [f"shim: already installed at {target}"]
    if dry_run:
        return [f"shim: would write {target}"]
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_preserving_mode(target, body)
    os.chmod(target, 0o755)
    actions = [f"shim: installed at {target}"]
    if str(target.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        actions.append(f"NOTE: add {target.parent} to PATH")
    return actions


def shim_on_path() -> bool:
    """True when `brain` resolves from PATH — the universal access layer."""
    return bool(shutil.which("brain"))


def guard_command(agent: str = "") -> str:
    """The enforcement hook command any agent with command hooks can call.

    Written as a shell conditional on purpose: a missing shim must not turn every tool
    call into a failure (the hook would block work for the wrong reason), but a real
    refusal must still propagate as a non-zero exit.
    """
    shim = shim_path()
    who = agent or "unknown"
    # `--stdin-json`: the client pipes the tool payload in, so the guard can refuse the
    # exact file that is leased by somebody else instead of blocking every write.
    tail = f"guard --agent {who} --stdin-json"
    if os.name == "nt":
        return f'"{shim}" {tail}'
    return f'if [ -x "{shim}" ]; then "{shim}" {tail}; fi'


OPENCODE_PLUGIN = r'''/**
 * brain-guard — no mutating tool runs without an open Second Brain session.
 *
 * Generated by `brain setup` from brain/agents.py; the logic lives in the CLI it
 * calls (`brain guard`), which resolves the workspace from the cwd, so this file
 * never needs to know where the vault or the project lives.
 *
 * Read-only tools always pass. Session lifecycle commands always pass, or you could
 * never open the session that clears the guard. `BRAIN_BYPASS=1` steps over the guard
 * only while trust is in bootstrap mode, and only the engine decides that: it knows the
 * trust mode, and it books the step to the event stream as self-granted. After trust is
 * installed a human mints one with `brain bypass-grant`.
 */
import { spawnSync } from "node:child_process"

const BRAIN = process.env.BRAIN_BIN || `${process.env.HOME}/.local/bin/brain`
const READONLY = new Set(["read", "glob", "grep", "list", "webfetch", "websearch", "skill"])
const CLEARANCE = /\bbrain\s+(start|end|guard|whoami|brief|bootstrap)\b/
// Read-only git inspection: every && / ; / || segment must be a non-mutating
// git subcommand. Deliberately excludes pull/push/merge/checkout/add/commit/reset/clean.
const READONLY_GIT = /^\s*git(\s+-C\s+\S+)*\s+(fetch|log|diff|status|rev-parse|show|ls-files|ls-remote|branch|tag|remote|grep|blame|stash\s+list|count-objects|verify-pack|var)\b/
// Second Brain session lifecycle + read-only query tools always pass.
// Otherwise an agent with no session can never open the session that clears
// the guard (same deadlock the CLEARANCE regex solves for bash).
const BRAIN_PASS = /^second-brain_brain_(start|end|update|reserve|check_files|whoami|brief|status|recall|read|tasks|sessions|runs|specs|next|route|verify|related|workspaces|doctor)\b/

export default async () => ({
  "tool.execute.before": async (input, output) => {
    if (READONLY.has(input.tool)) return
    if (BRAIN_PASS.test(input.tool)) return
    // No BRAIN_BYPASS check here on purpose. The engine's own gate is mode-aware -- it
    // honours BRAIN_BYPASS=1 only before trust is installed, and spends a signed grant
    // after -- and it writes down which one happened. A short-circuit in this file would
    // keep working after the boundary became real, which is the opposite of a bypass.
    if (input.tool === "bash") {
      const cmd = (output.args && output.args.command) || ""
      // Clearance must always be reachable, or the guard deadlocks the session.
      if (CLEARANCE.test(cmd)) return
      // Read-only git inspection needs no session (fetch/log/diff/status/...).
      const segments = cmd.split(/&&|\|\||;/)
      if (segments.length > 0 && segments.every((s) => READONLY_GIT.test(s))) return
    }
    // Pass the target path when the tool exposes one, so a lease held on a *different*
    // file does not block this edit.
    const args = (output && output.args) || {}
    const path = args.filePath || args.path || args.file_path || args.filename
    const argv = ["guard", "--agent", "opencode"]
    if (path) argv.push("--files", path)
    const res = spawnSync(BRAIN, argv, {
      cwd: process.cwd(),
      encoding: "utf8",
      timeout: 15000,
    })
    if (res.error) return // brain not installed => fail open
    if (res.status !== 0) {
      throw new Error((res.stderr || "").trim() || "[brain-guard] blocked: no session")
    }
  },
})
'''


# ---- the skill (the layer every modern agent discovers on its own) -------

SKILL_NAME = "second-brain"
SKILL_MARK = "name: second-brain"


def skill_body() -> str:
    """A `SKILL.md` that makes the brain self-announcing.

    Skills are the one integration point that needs no config file, no restart and no
    per-agent wiring: Freebuff/Codebuff, Claude Code and anything else following the
    convention scan `.agents/skills/` and `~/.agents/skills/` on their own and let the
    model load a skill by name when the description matches. So this file is written
    for the model to read, in the model's own vocabulary, and the description is
    loaded with the triggers that mean "this task is about shared state".
    """
    return f'''---
name: {SKILL_NAME}
description: >-
  Shared memory, task board and multi-agent coordination for this machine. Load this
  at the start of any non-trivial coding task, and any time the user mentions the
  second brain, "the brain", other agents, handoffs, file leases, claims, workspaces,
  who is working on what, what we already learned/decided, or resuming previous work.
  It explains how to read the knowledge other agents recorded and how to record yours
  so nothing is re-derived twice.
---

# Second Brain — shared memory for coding agents

Every agent on this machine (Codex, Claude Code, opencode, Antigravity, Freebuff, …)
reads and writes one vault. What one agent proves, the next one recalls instead of
re-discovering. Vault: `{VAULT}`

## Do this first

```bash
brain whoami          # which agent + workspace the brain sees (workspace comes from cwd)
brain brief           # your context: open leases, board, recent notes, top claims
```

If `brain` is not on PATH, use `python3 {VAULT / "engine.py"} <command>`.

## The loop

1. **Claim before you build.** `brain start --agent <you> --task "..." --files a.py,b.py`
   opens a session and leases the files you will write. A lease another agent already
   holds is **refused**, so this is how two agents avoid clobbering each other. Missing
   `--files` is the single most common mistake — pass every path you will edit.
   Do this yourself at the start of every task — never ask the human to run
   `brain start` for you. A guard refusal means *you* open a session, not an
   error to report.
2. **Check before you touch.** `brain check-files path1 path2` before editing files you
   did not lease.
3. **Ask the knowledge base first.** `brain recall "how does auth work"` (BM25 over
   every claim, spec, task and note). Cheaper and more accurate than re-deriving it.
4. **Post while you work.** `brain post "..."` is a live scratchpad the other agents
   see immediately — findings, blockers, "I am about to change the schema".
5. **Record what you proved.** `brain claim "..." --source <file-or-command> --confidence
   0.9` for anything durable — confidence is a number, not a word. Claims are the actual
   knowledge base; `--global` shares one with every workspace.
6. **Hand off explicitly.** `brain end <session-id> --summary "..." --test-status
   "pytest: 12 passed" --target-agent <next>`. A card cannot move to `done` without a
   finished session that recorded a test status or a handoff.

## Workspaces (how knowledge stays separated)

The workspace is **auto-detected from your cwd** — a `.brain-workspace` marker,
`git config brain.workspace`, or the registered project path. Work on a project lands
in that project's workspace and is invisible to unrelated ones; `global` holds truth
shared by everything. Override with `brain ... --workspace <slug>`, list them with
`brain workspaces`.

## Board

`brain tasks` shows the kanban. `brain next` says what to do now. `brain move <id>
<status>` advances a card: `backlog -> planning -> running -> review -> done`.

## Rules that are enforced, not suggested

- mutating files without a session **of your own** is blocked (`brain guard`); another
  agent's session does not authorise your writes. `BRAIN_BYPASS=1` steps over that only
  while trust is in bootstrap mode (`brain attest` says which mode you are in), and the
  brain books it as self-granted rather than human-authorised; after trust is installed
  the only way over is a human minting you a single-use token with `brain bypass-grant`.
- leasing a file another live agent holds is refused — parallel work on *different*
  files is allowed and is the normal case
- a card cannot reach `done` without review evidence

Run `brain bootstrap` for the long form, `brain doctor` if anything looks wrong.
'''


def skill_dirs(project_root: str = "") -> list:
    """Where a SKILL.md is discovered, project-local first.

    Project-local wins for two reasons: it is always searched (home skills depend on an
    `includeHomeSkills` setting in some clients), and it travels with the repo, so a
    teammate or a fresh clone gets the integration without running anything.
    """
    dirs = []
    if project_root:
        root = Path(project_root).expanduser()
        dirs += [root / ".agents" / "skills", root / ".claude" / "skills"]
    dirs += [HOME / ".agents" / "skills", HOME / ".claude" / "skills"]
    return [d / SKILL_NAME for d in dirs]


def install_skill(actions: list, dry_run: bool = False, project_root: str = "") -> None:
    """Write the skill everywhere it will be picked up. Idempotent."""
    body = skill_body()
    project_root = str(Path(project_root).expanduser()) if project_root else ""
    for directory in skill_dirs(project_root):
        target = directory / "SKILL.md"
        inside_project = bool(project_root) and str(target).startswith(project_root + os.sep)
        label = (f"project skill ({Path(project_root).name})" if inside_project else "skill")
        if target.exists() and read_text(target) == body:
            actions.append(f"{label}: {target} up to date")
            continue
        if dry_run:
            actions.append(f"{label}: would write {target}")
            continue
        try:
            _backup(target)
            _write_preserving_mode(target, body)
            actions.append(f"{label}: installed at {target}")
        except OSError as exc:
            actions.append(f"{label}: FAILED ({exc})")


def skill_targets() -> list:
    """Paths that should exist for the "any agent finds the brain" promise to hold."""
    return [d / "SKILL.md" for d in skill_dirs()]


def skill_installed() -> bool:
    """True when at least one global skill copy is present and current."""
    body = skill_body()
    return any(p.exists() and read_text(p) == body for p in skill_targets())


# ---- the paste-in brief --------------------------------------------------


def bootstrap_brief(agent: str = "", workspace: str = "") -> str:
    """One text block that teaches any agent how to use the brain.

    Written to AGENTS.md, served at /agent/bootstrap, and printed by `brain bootstrap`,
    so hosted agents with no local config still get the full protocol.
    """
    detected = workspace or "auto-detected from your cwd"
    return f"""# Second Brain — agent integration

Shared memory + task board + coordination for every coding agent on this machine.
Vault: `{VAULT}`  |  Generated {now()} by `brain setup`; do not edit by hand.

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
`python3 {VAULT / "engine.py"} <command>`.

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
Your brief prints them as two labelled sections. Detected workspace: `{detected}`.

## MCP (if your agent supports it)

`brain setup` writes the server entry into Claude, Codex, opencode, Gemini/Antigravity
and Crush configs automatically, and installs the skill everywhere it is discovered.
The server is `second-brain` and is started with:

```
{json.dumps(mcp_server_entry()["args"][0])}
```

`brain doctor` verifies all of the above end to end.
"""


# ---- shared PATH env for dispatched agents -------------------------------


def child_env(workspace: str = "") -> dict:
    """Environment every dispatched agent inherits so it lands in the right workspace."""
    env = dict(os.environ)
    env["SECOND_BRAIN_VAULT"] = str(VAULT)
    if workspace:
        env["SECOND_BRAIN_WORKSPACE"] = ws_mod.resolve_alias(workspace)
    bin_dir = str(shim_path().parent)
    if bin_dir not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def write_user_vault_pointer(dry_run: bool = False) -> list:
    """Mirror the vault location to ~/.config/second-brain/vault for the shim."""
    if USER_CONFIG.exists() and read_text(USER_CONFIG).strip() == str(VAULT):
        return []
    if dry_run:
        return [f"vault pointer: would write {USER_CONFIG}"]
    _write_preserving_mode(USER_CONFIG, str(VAULT) + "\n")
    return [f"vault pointer: {USER_CONFIG} -> {VAULT}"]
