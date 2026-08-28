#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain_mcp.py - MCP bridge exposing the second-brain to any MCP client (v4.3).
(opencode, Hermes, Claude Code, Antigravity, Codex, ...).

Tools (28 total):
  Autonomous Dispatch: brain_dispatch, brain_auto_cycle, brain_cycle_route, brain_cycle_next
  Specs & Planning:    brain_spec_create, brain_specs
  Kanban Tasks:        brain_task_create, brain_task_move, brain_tasks
  Coordination:        brain_session_start, brain_session_update, brain_session_end,
                       brain_sessions, brain_reserve, brain_check_files,
                       brain_post, brain_read, brain_dashboard
  Knowledge/Memory:    brain_status, brain_recall, brain_claim, brain_supersede,
                       brain_dispute, brain_verify, brain_related, brain_promote, brain_sweep
"""
import io
import os
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

VAULT = os.environ.get("SECOND_BRAIN_VAULT", r"D:\projects\second-brain")
sys.path.insert(0, VAULT)
import engine  # noqa: E402

mcp = FastMCP("second-brain")


def _run(handler, **kwargs):
    args = SimpleNamespace(**kwargs)
    try:
        with engine.lock():
            cfg = engine.load_config()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = handler(args, cfg)
            out = buf.getvalue().strip()
        return out or f"(no output, exit {code})"
    except FileNotFoundError as e:
        return f"ERROR: file not found — {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# ================ AUTONOMOUS PIPELINE & DISPATCH ================

@mcp.tool()
def brain_dispatch(task_id: str, agent: str = "", open_tab: bool = False) -> str:
    """Directly invoke the assigned agent CLI (Codex, opencode, Claude, AGY) for a specific task.
    - open_tab: if True, launches in a new Windows Terminal / PowerShell tab so you can watch."""
    return _run(engine.cmd_dispatch, id=task_id, agent=agent, tab=open_tab)


@mcp.tool()
def brain_auto_cycle(project: str = "", open_tab: bool = False) -> str:
    """Inspect the live Kanban board and dispatch the highest-priority actionable task automatically."""
    return _run(engine.cmd_auto_cycle, project=project, tab=open_tab)


@mcp.tool()
def brain_cycle_route(agent: str, prompt: str, project: str = "") -> str:
    """Evaluate a user request and determine whether to execute directly or activate
    the 4-stage pipeline: Codex (Planner) -> opencode/Claude (Builder) -> Antigravity (Reviewer)."""
    return _run(engine.cmd_cycle_route, agent=agent, prompt=prompt, project=project)


@mcp.tool()
def brain_cycle_next(agent: str, project: str = "") -> str:
    """Inspect the live Kanban board and get the exact next actionable step for this agent."""
    return _run(engine.cmd_cycle_next, agent=agent, project=project)


# ================ UPSTREAM SPECS & PLANNING (Traycer) ================

@mcp.tool()
def brain_spec_create(title: str, spec: str, project: str = "", phases: str = "") -> str:
    """Create an upstream architecture spec with phased milestones before editing code."""
    return _run(engine.cmd_spec_create, title=title, spec=spec, project=project, phases=phases)


@mcp.tool()
def brain_specs(project: str = "") -> str:
    """List upstream architecture specs and their execution phases."""
    return _run(engine.cmd_specs, project=project)


# ================ KANBAN TASKS (agtx) ================

@mcp.tool()
def brain_task_create(title: str, project: str = "", spec_id: str = "",
                      agent: str = "", phase: str = "", files: str = "") -> str:
    """Create a new task on the Git-backed Kanban board in the [backlog] column."""
    return _run(engine.cmd_task_create, title=title, project=project,
                spec=spec_id, agent=agent, phase=phase, files=files)


@mcp.tool()
def brain_task_move(task_id: str, status: str, agent: str = "", notes: str = "") -> str:
    """Advance a task on the Kanban board (backlog -> planning -> running -> review -> done)."""
    return _run(engine.cmd_task_move, id=task_id, status=status, agent=agent, notes=notes)


@mcp.tool()
def brain_tasks(project: str = "", status: str = "", agent: str = "") -> str:
    """View the Kanban board columns (backlog, planning, running, review, done)."""
    return _run(engine.cmd_tasks, project=project, status=status, agent=agent)


# ================ COORDINATION & CONCURRENCY ================

@mcp.tool()
def brain_session_start(agent: str, project: str = "", task: str = "",
                        task_id: str = "", files: str = "", lease_mins: int = 30,
                        branch: str = "", worktree: str = "") -> str:
    """Register this agent's active session with optional file reservations, git branch, and worktree."""
    return _run(engine.cmd_session_start, agent=agent, project=project, task=task,
                task_id=task_id, files=files, lease=lease_mins, branch=branch, worktree=worktree)


@mcp.tool()
def brain_session_update(session_id: str, progress: str = "", files: str = "",
                        extend_lease_mins: int = 0) -> str:
    """Append a progress milestone or update/extend file reservations on your active session."""
    return _run(engine.cmd_session_update, id=session_id, progress=progress,
                files=files, extend_lease=extend_lease_mins)


@mcp.tool()
def brain_session_end(session_id: str, summary: str = "", target_agent: str = "",
                      next_steps: str = "", modified_files: str = "",
                      test_status: str = "") -> str:
    """End your session and release all file locks. Record structured handoff details."""
    return _run(engine.cmd_session_end, id=session_id, summary=summary,
                target_agent=target_agent, next_steps=next_steps,
                modified_files=modified_files, test_status=test_status)


@mcp.tool()
def brain_sessions(project: str = "", agent: str = "",
                   active_only: bool = True) -> str:
    """See what other agents are doing, active file locks, or recent handoffs."""
    return _run(engine.cmd_sessions, project=project, agent=agent,
                active=active_only)


@mcp.tool()
def brain_reserve(session_id: str, files: str, lease_mins: int = 30) -> str:
    """Claim a temporary lease/lock on specific files for your active session."""
    return _run(engine.cmd_reserve, id=session_id, files=files, lease=lease_mins)


@mcp.tool()
def brain_check_files(files: str, project: str = "") -> str:
    """Check if specific files are currently locked by another agent before editing."""
    return _run(engine.cmd_check_files, files=files, project=project)


@mcp.tool()
def brain_post(text: str, project: str = "", tags: str = "",
               agent: str = "") -> str:
    """Share a discovery, decision, or blocker with all agents (7-day TTL)."""
    return _run(engine.cmd_post, text=text, project=project, tags=tags,
                agent=agent)


@mcp.tool()
def brain_read(query: str = "", project: str = "", agent: str = "",
               tag: str = "", limit: int = 20) -> str:
    """Read shared context notes with BM25 full-text search."""
    return _run(engine.cmd_read, query=query, project=project, agent=agent,
                tag=tag, limit=limit)


@mcp.tool()
def brain_dashboard() -> str:
    """Full situational awareness: Kanban board, active sessions, live file leases,
    recent handoffs, recent context notes, and vault health."""
    return _run(engine.cmd_dashboard)


# ================ KNOWLEDGE & CLAIMS ================

@mcp.tool()
def brain_status() -> str:
    """Vault health: claim counts, active tasks, active sessions, file locks, L0 budget."""
    return _run(engine.cmd_status)


@mcp.tool()
def brain_recall(query: str = "", tag: str = "", status: str = "",
                 show_all: bool = False) -> str:
    """Deterministic BM25 full-text recall over stored claims (powered by SQLite FTS5)."""
    return _run(engine.cmd_recall, query=query, tag=tag, status=status,
                **{"all": show_all})


@mcp.tool()
def brain_claim(text: str, confidence: float = 0.9, source: str = "",
                tags: str = "", status: str = "active") -> str:
    """Record a permanent claim (fact, preference, hard rule) into the shared brain."""
    return _run(engine.cmd_claim, text=text, confidence=confidence,
                source=source, tags=tags, status=status)


@mcp.tool()
def brain_supersede(old_id: str, new_id: str) -> str:
    """Mark claim <old_id> superseded by claim <new_id> (chain-aware)."""
    return _run(engine.cmd_supersede, id=old_id, newid=new_id)


@mcp.tool()
def brain_dispute(claim_id: str, reason: str = "", by: str = "") -> str:
    """Mark a claim disputed, keeping its evidence. Requires a reason."""
    return _run(engine.cmd_dispute, id=claim_id, reason=reason, by=by)


@mcp.tool()
def brain_promote(context_id: str, confidence: float = 0.9, tags: str = "") -> str:
    """Promote an ephemeral context note into a permanent claim in claims/*.md."""
    return _run(engine.cmd_promote, id=context_id, confidence=confidence, tags=tags)


@mcp.tool()
def brain_verify(claim_id: str) -> str:
    """Chain-integrity check for one claim."""
    return _run(engine.cmd_verify, id=claim_id)


@mcp.tool()
def brain_related(claim_id: str) -> str:
    """Graph traversal: claims related to <claim_id> via shared tags, wikilinks, or supersede edges."""
    return _run(engine.cmd_related, id=claim_id)


@mcp.tool()
def brain_sweep(commit: bool = False) -> str:
    """Housekeeping: expire stale sessions, archive old context notes, reindex FTS5, and rebuild L0."""
    return _run(engine.cmd_sweep, commit=commit)


if __name__ == "__main__":
    mcp.run(transport="stdio")
