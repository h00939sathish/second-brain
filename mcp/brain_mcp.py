#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Second Brain MCP bridge.

Exposes the vault to any MCP client (Claude Code, Codex, opencode, Antigravity,
Crush, ...). Everything delegates to `brain.cli`, so the MCP surface and the `brain`
CLI can never drift apart — there is one implementation of each behaviour.

Tools (30):
  Onboarding   brain_bootstrap, brain_whoami, brain_doctor
  Workspaces   brain_workspaces
  Session      brain_start, brain_update, brain_reserve, brain_check_files,
               brain_end, brain_sessions
  Scratchpad   brain_post, brain_read
  Knowledge    brain_recall, brain_claim, brain_elevate, brain_review, brain_dispute,
               brain_supersede, brain_promote, brain_related, brain_verify
  Board        brain_task_create, brain_move, brain_tasks, brain_next,
               brain_spec_create, brain_specs
  Execution    brain_dispatch, brain_auto_cycle, brain_route, brain_runs
  Maintenance  brain_status, brain_sweep
"""

import io
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace

DEFAULT_VAULT = str(Path(__file__).resolve().parent.parent)
VAULT = os.environ.get("SECOND_BRAIN_VAULT", DEFAULT_VAULT)
sys.path.insert(0, VAULT)

from brain import cli, store  # noqa: E402
from brain.errors import BrainError, LeaseConflict, NotFound, ReviewGate  # noqa: E402
from brain.paths import lock  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # a clear error beats a stack trace
    sys.stderr.write(
        "the 'mcp' package is missing from this interpreter.\n"
        "fix: cd mcp && uv venv --python 3.11 .venv && uv pip install --python .venv 'mcp<2'\n"
        "or just run: brain setup\n"
    )
    raise

mcp = FastMCP("second-brain")

_READ_ONLY = {
    cli.cmd_status, cli.cmd_doctor, cli.cmd_whoami, cli.cmd_brief, cli.cmd_bootstrap,
    cli.cmd_recall, cli.cmd_related, cli.cmd_verify, cli.cmd_tasks, cli.cmd_specs,
    cli.cmd_sessions, cli.cmd_read, cli.cmd_workspaces, cli.cmd_runs, cli.cmd_guard,
}
# Handlers whose arguments do not exist in the shared default set.
_DEFAULTS = {
    "workspace": "", "agent": "", "project": "", "task": "", "task_id": "", "files": "",
    "branch": "", "worktree": "", "lease": 0, "force": False, "status": "", "reason": "",
    "by": "", "summary": "", "target_agent": "", "next_steps": "", "modified_files": "",
    "test_status": "", "progress": "", "extend_lease": 0, "active": False, "tags": "",
    "confidence": 0.9, "source": "", "spec": "", "phases": "", "title": "", "text": "",
    "query": "", "tag": "", "id": "", "newid": "", "prompt": "", "limit": 0,
    "all_workspaces": False, "all": False, "global_scope": False, "note": "", "tests": "",
    "commit": False, "json": False, "action": "list", "name": "", "path": "",
    "description": "", "default": False, "no_git": False, "tab": False, "wait": False,
    "timeout": 0, "verbose": False, "write": False, "dry_run": False, "no_shim": False,
    "bind": "", "no_commit": False, "once": False, "interval": 15, "max_retries": 3,
    "port": 8000, "host": "127.0.0.1", "scope": "",
}


def _run(handler, **kwargs):
    """Invoke a cli handler and return its text output to the MCP client."""
    merged = dict(_DEFAULTS)
    merged.update(kwargs)
    args = SimpleNamespace(**merged)
    out = cli.Out(as_json=False)
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        cfg = store.config()
        if handler in _READ_ONLY:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = handler(args, out, cfg)
        else:
            with lock(), redirect_stdout(stdout), redirect_stderr(stderr):
                code = handler(args, out, cfg)
        text = "\n".join(p for p in (stdout.getvalue().strip(),
                                     stderr.getvalue().strip()) if p)
        return text or f"(no output, exit {code})"
    except ReviewGate as exc:
        return f"REFUSED (review gate): {exc}"
    except LeaseConflict as exc:
        return f"REFUSED (lease conflict): {exc}"
    except NotFound as exc:
        return f"not found: {exc}"
    except BrainError as exc:
        return f"error: {exc}"
    except Exception as exc:  # noqa: BLE001 — never kill the MCP session
        return f"ERROR: {type(exc).__name__}: {exc}"


# ---- onboarding ----------------------------------------------------------


@mcp.tool()
def brain_bootstrap(agent: str = "", workspace: str = "") -> str:
    """Read this first. How to use the shared brain: the protocol, the commands, and
    which workspace you are in. Works without any other setup."""
    return _run(cli.cmd_bootstrap, agent=agent, workspace=workspace)


@mcp.tool()
def brain_whoami(agent: str = "", workspace: str = "") -> str:
    """What the brain thinks you are (agent + role), which workspace you are in, and
    whether you have an open session."""
    return _run(cli.cmd_whoami, agent=agent, workspace=workspace)


@mcp.tool()
def brain_doctor() -> str:
    """Diagnose the installation: index, git, agent CLIs, MCP configs, daemon, problems."""
    return _run(cli.cmd_doctor)


@mcp.tool()
def brain_workspaces(action: str = "list", name: str = "", path: str = "",
                     description: str = "", default: bool = False) -> str:
    """List, add, bind or remove workspaces. Work is scoped per workspace so different
    projects never see each other's knowledge; `--scope global` claims are shared."""
    return _run(cli.cmd_workspaces, action=action, name=name, path=path,
                description=description, default=default)


# ---- sessions & coordination --------------------------------------------


@mcp.tool()
def brain_start(agent: str, project: str = "", task: str = "", task_id: str = "",
                files: str = "", branch: str = "", worktree: str = "", lease_mins: int = 30,
                workspace: str = "", force: bool = False) -> str:
    """Open a session and lease the files you are about to touch. Files already leased
    by another live session are refused, which is how agents avoid clobbering each other."""
    return _run(cli.cmd_start, agent=agent, project=project, task=task, task_id=task_id,
                files=files, branch=branch, worktree=worktree, lease=lease_mins,
                workspace=workspace, force=force)


@mcp.tool()
def brain_update(session_id: str, progress: str = "", files: str = "",
                 extend_lease_mins: int = 0, workspace: str = "") -> str:
    """Record a progress milestone, or extend/replace your file leases."""
    return _run(cli.cmd_update, id=session_id, progress=progress, files=files,
                extend_lease=extend_lease_mins, workspace=workspace)


@mcp.tool()
def brain_reserve(session_id: str, files: str, lease_mins: int = 30,
                  workspace: str = "") -> str:
    """Lease additional files mid-session, before you edit them."""
    return _run(cli.cmd_reserve, id=session_id, files=files, lease=lease_mins,
                workspace=workspace)


@mcp.tool()
def brain_check_files(files: str) -> str:
    """Ask whether these files are free before you edit them."""
    return _run(cli.cmd_check_files, files=files)


@mcp.tool()
def brain_end(session_id: str, summary: str = "", target_agent: str = "",
              next_steps: str = "", modified_files: str = "", test_status: str = "",
              workspace: str = "") -> str:
    """Close your session, release leases and hand off explicitly. Recording tests or a
    reviewer handoff is what later permits the card to reach [done]."""
    return _run(cli.cmd_end, id=session_id, summary=summary, target_agent=target_agent,
                next_steps=next_steps, modified_files=modified_files,
                test_status=test_status, workspace=workspace)


@mcp.tool()
def brain_sessions(agent: str = "", project: str = "", active_only: bool = False,
                   workspace: str = "", all_workspaces: bool = False) -> str:
    """Who is working on what right now, and which files they hold."""
    return _run(cli.cmd_sessions, agent=agent, project=project, active=active_only,
                workspace=workspace, all_workspaces=all_workspaces)


# ---- scratchpad ----------------------------------------------------------


@mcp.tool()
def brain_post(text: str, project: str = "", tags: str = "", topic: str = "",
               agent: str = "", to: str = "", workspace: str = "") -> str:
    """Post a note or topic message other agents can read immediately. If `to` is given,
    routes as an attested direct message to the recipient's inbox."""
    return _run(cli.cmd_post, text=text, project=project, tags=tags, topic=topic,
                agent=agent, to=to, workspace=workspace)


@mcp.tool()
def brain_read(query: str = "", project: str = "", agent: str = "", tag: str = "",
               topic: str = "", limit: int = 0, workspace: str = "",
               all_workspaces: bool = False) -> str:
    """Read recent context notes or topic messages, newest first."""
    return _run(cli.cmd_read, query=query, project=project, agent=agent, tag=tag,
                topic=topic, limit=limit, workspace=workspace, all_workspaces=all_workspaces)


@mcp.tool()
def brain_wait(topic: str = "", agent: str = "", after: str = "", timeout: int = 60,
               workspace: str = "", all_workspaces: bool = False) -> str:
    """Block execution until new context notes or topic messages arrive, or until timeout expires.
    Prevents burning tokens in tight polling loops while waiting for a peer agent to reply."""
    return _run(cli.cmd_wait, topic=topic, agent=agent, after=after, timeout=timeout,
                workspace=workspace, all_workspaces=all_workspaces)


# ---- knowledge -----------------------------------------------------------


@mcp.tool()
def brain_recall(query: str = "", tag: str = "", status: str = "", maturity: str = "",
                 limit: int = 0, include_withheld: bool = False, workspace: str = "",
                 all_workspaces: bool = False) -> str:
    """Search the knowledge base (BM25). Scoped to your workspace plus shared truth.
    Superseded/disputed claims are withheld from the results by default.
    Optional maturity filter: 'provisional', 'established', 'canonical'."""
    return _run(cli.cmd_recall, query=query, tag=tag, status=status, maturity=maturity,
                limit=limit, all=include_withheld, workspace=workspace,
                all_workspaces=all_workspaces)


@mcp.tool()
def brain_claim(text: str, source: str = "", tags: str = "", confidence: float = 0.9,
                maturity: str = "", scope: str = "", workspace: str = "") -> str:
    """Record a durable fact others can rely on. Pass source (a path, command or test
    output) and scope='global' when it applies to every workspace.
    Optional maturity: 'provisional', 'established', 'canonical'."""
    return _run(cli.cmd_claim, text=text, source=source, tags=tags, confidence=confidence,
                maturity=maturity, global_scope=str(scope).lower() == "global",
                workspace=workspace)


@mcp.tool()
def brain_elevate(claim_id: str, maturity: str = "canonical", note: str = "") -> str:
    """Elevate a claim along the epistemic maturity ladder ('provisional' -> 'established' -> 'canonical')."""
    return _run(cli.cmd_elevate, id=claim_id, maturity=maturity, note=note)


@mcp.tool()
def brain_review(claim_id: str, note: str = "") -> str:
    """Mark a claim as verified now. This is the only thing that resets its staleness
    clock, so sweep can tell reviewed knowledge from forgotten knowledge."""
    return _run(cli.cmd_review, id=claim_id, note=note)


@mcp.tool()
def brain_dispute(claim_id: str, reason: str = "", by: str = "") -> str:
    """Keep a claim's evidence but stop trusting it."""
    return _run(cli.cmd_dispute, id=claim_id, reason=reason, by=by)


@mcp.tool()
def brain_supersede(claim_id: str, new_claim_id: str) -> str:
    """Replace a claim with a newer one, linking both directions."""
    return _run(cli.cmd_supersede, id=claim_id, newid=new_claim_id)


@mcp.tool()
def brain_promote(context_id: str, confidence: float = 0.9, tags: str = "") -> str:
    """Promote a context note into a durable claim, keeping the note's full text."""
    return _run(cli.cmd_promote, id=context_id, confidence=confidence, tags=tags)


@mcp.tool()
def brain_related(claim_id: str) -> str:
    """Claims linked to this one by tag, wikilink or supersede chain."""
    return _run(cli.cmd_related, id=claim_id)


@mcp.tool()
def brain_verify(claim_id: str = "") -> str:
    """Check schema, chains, wikilinks and frontmatter round-trip. Empty id = whole vault."""
    return _run(cli.cmd_verify, id=claim_id)


# ---- board ---------------------------------------------------------------


@mcp.tool()
def brain_task_create(title: str, project: str = "", spec_id: str = "", agent: str = "",
                      phase: str = "", files: str = "", workspace: str = "") -> str:
    """Add a card to the board in [backlog]."""
    return _run(cli.cmd_task_create, title=title, project=project, spec=spec_id, agent=agent,
                phase=phase, files=files, workspace=workspace)


@mcp.tool()
def brain_move(task_id: str, status: str, agent: str = "", notes: str = "",
               tests: str = "", workspace: str = "") -> str:
    """Advance a card: backlog -> planning -> running -> review -> done. The move to
    [done] is refused unless a finished session recorded tests or a reviewer handoff."""
    return _run(cli.cmd_move, id=task_id, status=status, agent=agent, notes=notes,
                tests=tests, workspace=workspace)


@mcp.tool()
def brain_tasks(project: str = "", status: str = "", agent: str = "",
                workspace: str = "", all_workspaces: bool = False) -> str:
    """The board, grouped by column."""
    return _run(cli.cmd_tasks, project=project, status=status, agent=agent,
                workspace=workspace, all_workspaces=all_workspaces)


@mcp.tool()
def brain_next(agent: str, project: str = "", workspace: str = "") -> str:
    """The next actionable step for you right now, based on your role and the board."""
    return _run(cli.cmd_next, agent=agent, project=project, workspace=workspace)


@mcp.tool()
def brain_spec_create(title: str, spec: str, project: str = "", phases: str = "",
                      workspace: str = "") -> str:
    """Write the upstream spec (intent, constraints, phases) before code is touched."""
    return _run(cli.cmd_spec_create, title=title, spec=spec, project=project, phases=phases,
                workspace=workspace)


@mcp.tool()
def brain_specs(project: str = "", workspace: str = "",
                all_workspaces: bool = False) -> str:
    """List specs and their phases."""
    return _run(cli.cmd_specs, project=project, workspace=workspace,
                all_workspaces=all_workspaces)


# ---- execution -----------------------------------------------------------


@mcp.tool()
def brain_dispatch(task_id: str, agent: str = "", open_tab: bool = False,
                   workspace: str = "", wait: bool = False) -> str:
    """Run the assigned agent CLI on a card, headless in the background (or in a
    terminal window with open_tab). Refuses when the card is already in flight."""
    return _run(cli.cmd_dispatch, id=task_id, agent=agent, tab=open_tab,
                workspace=workspace, wait=wait)


@mcp.tool()
def brain_auto_cycle(project: str = "", workspace: str = "", open_tab: bool = False) -> str:
    """Dispatch the next actionable card exactly once. Skips cards that already have a
    live session or process, and trips a circuit breaker after repeated attempts."""
    return _run(cli.cmd_auto_cycle, project=project, workspace=workspace, tab=open_tab)


@mcp.tool()
def brain_route(agent: str, prompt: str, project: str = "", workspace: str = "") -> str:
    """Decide whether a request is lightweight (do it here) or needs the full
    planner -> builder -> reviewer pipeline, with the reasons spelled out."""
    return _run(cli.cmd_route, agent=agent, prompt=prompt, project=project,
                workspace=workspace)


@mcp.tool()
def brain_runs(limit: int = 10, workspace: str = "") -> str:
    """Dispatch history with real exit codes."""
    return _run(cli.cmd_runs, limit=limit, workspace=workspace)


@mcp.tool()
def brain_squad(action: str = "show", role: str = "", agent: str = "", name: str = "",
                workspace: str = "") -> str:
    """View or manage the workspace agent squad (roles: lead, builder, reviewer, qa).
    Action can be 'show', 'init', or 'set'."""
    return _run(cli.cmd_squad, action=action, role=role, agent=agent, name=name, workspace=workspace)


# ---- maintenance ---------------------------------------------------------


@mcp.tool()
def brain_status(workspace: str = "") -> str:
    """Vault health: claims, board, live sessions, leases, daemon state, L0 budget."""
    return _run(cli.cmd_status, workspace=workspace)


@mcp.tool()
def brain_sweep(commit: bool = False) -> str:
    """Housekeeping: close abandoned sessions, archive old notes, flag unreviewed
    claims, rebuild the L0 brief."""
    return _run(cli.cmd_sweep, commit=commit)


@mcp.tool()
def brain_brief(workspace: str = "") -> str:
    """The compact brief for your workspace: live sessions, board, recent notes and the
    highest-value claims. Read it instead of grepping the vault."""
    return _run(cli.cmd_brief, workspace=workspace)


if __name__ == "__main__":
    mcp.run()
