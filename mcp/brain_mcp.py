#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain_mcp.py - MCP bridge exposing the second-brain to any MCP client
(opencode, Hermes, Claude Code, Antigravity, Codex, ...).

Every tool wraps the deterministic engine (engine.py), so all agents
mutate one shared git-backed truth store + multi-agent coordination layer.

Deterministic only: no external LLM. SQLite FTS5 (BM25) fast search.

Tools (19 total):
  Knowledge:  brain_status, brain_recall, brain_claim, brain_supersede,
              brain_dispute, brain_verify, brain_related, brain_promote, brain_sweep
  Coordination: brain_session_start, brain_session_update, brain_session_end,
                brain_sessions, brain_reserve, brain_check_files,
                brain_post, brain_read, brain_dashboard
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
    """Run one engine command under the vault lock, returning its stdout.

    All handlers are lock-free by contract (see engine.py INVARIANT comment).
    This function is the single place where the lock is acquired for MCP calls.
    """
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


# ================ KNOWLEDGE & CLAIMS TOOLS ================

@mcp.tool()
def brain_status() -> str:
    """Vault health: claim counts, active sessions, active file locks, context
    notes, chain integrity, L0 budget. Call to see overall brain state."""
    return _run(engine.cmd_status)


@mcp.tool()
def brain_recall(query: str = "", tag: str = "", status: str = "",
                 show_all: bool = False) -> str:
    """Deterministic BM25 full-text recall over stored claims (powered by SQLite FTS5).
    Expired/superseded/disputed claims are withheld by default (show_all=True includes
    them, clearly marked). Call this before answering questions about the user's past
    work, preferences, or project facts."""
    return _run(engine.cmd_recall, query=query, tag=tag, status=status,
                **{"all": show_all})


@mcp.tool()
def brain_claim(text: str, confidence: float = 0.9, source: str = "",
                tags: str = "", status: str = "active") -> str:
    """Record a permanent claim (fact, preference, hard rule, outcome) into the shared
    brain. Git commit is made automatically (audit trail). Use source to name where the
    fact came from, tags for associative linking."""
    return _run(engine.cmd_claim, text=text, confidence=confidence,
                source=source, tags=tags, status=status)


@mcp.tool()
def brain_supersede(old_id: str, new_id: str) -> str:
    """Mark claim <old_id> superseded by claim <new_id> (chain-aware). Use when
    newer evidence replaces an older claim."""
    return _run(engine.cmd_supersede, id=old_id, newid=new_id)


@mcp.tool()
def brain_dispute(claim_id: str, reason: str = "", by: str = "") -> str:
    """Mark a claim disputed, keeping its evidence. Requires a reason."""
    return _run(engine.cmd_dispute, id=claim_id, reason=reason, by=by)


@mcp.tool()
def brain_promote(context_id: str, confidence: float = 0.9, tags: str = "") -> str:
    """Promote an ephemeral context note into a permanent claim in claims/*.md.
    Use when a temporary discovery/decision proves valuable for long-term memory."""
    return _run(engine.cmd_promote, id=context_id, confidence=confidence, tags=tags)


@mcp.tool()
def brain_verify(claim_id: str) -> str:
    """Chain-integrity check for one claim (dangling/cycle references)."""
    return _run(engine.cmd_verify, id=claim_id)


@mcp.tool()
def brain_related(claim_id: str) -> str:
    """Graph traversal: claims related to <claim_id> via shared tags, wikilinks,
    or supersede edges."""
    return _run(engine.cmd_related, id=claim_id)


@mcp.tool()
def brain_sweep(commit: bool = False) -> str:
    """Housekeeping: expire stale sessions (>24h), archive old context notes (>7d),
    rebuild the SQLite FTS5 search index, and rebuild the budget-aware L0 pointer set.
    commit=True also makes a git commit."""
    return _run(engine.cmd_sweep, commit=commit)


# ================ COORDINATION & CONCURRENCY TOOLS ================

@mcp.tool()
def brain_session_start(agent: str, project: str = "", task: str = "",
                        files: str = "", lease_mins: int = 30,
                        branch: str = "", worktree: str = "") -> str:
    """Register this agent's active session with optional file reservations and git branch.
    Call at the START of every conversation so other agents know what you're working on.
    - files: comma-separated paths to reserve (e.g. 'src/models.py,tests/test_models.py')
    - lease_mins: lease duration in minutes (default 30)
    Returns session ID — save for session_update/session_end."""
    return _run(engine.cmd_session_start, agent=agent, project=project, task=task,
                files=files, lease=lease_mins, branch=branch, worktree=worktree)


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
    """End your session and release all file locks. Record structured handoff details
    so the next agent picking up this work has exact context on what changed and what to do next."""
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
    """Claim a temporary lease/lock on specific files for your active session.
    files: comma-separated list of relative file paths."""
    return _run(engine.cmd_reserve, id=session_id, files=files, lease=lease_mins)


@mcp.tool()
def brain_check_files(files: str, project: str = "") -> str:
    """Check if specific files are currently locked by another agent before editing.
    files: comma-separated list of relative file paths. Returns 0 if clear, warns if locked."""
    return _run(engine.cmd_check_files, files=files, project=project)


@mcp.tool()
def brain_post(text: str, project: str = "", tags: str = "",
               agent: str = "") -> str:
    """Share a discovery, decision, or blocker with all agents. Lightweight note
    with 7-day TTL (can be promoted to permanent claim via brain_promote)."""
    return _run(engine.cmd_post, text=text, project=project, tags=tags,
                agent=agent)


@mcp.tool()
def brain_read(query: str = "", project: str = "", agent: str = "",
               tag: str = "", limit: int = 20) -> str:
    """Read shared context notes with BM25 full-text search. Filter by project, agent, or tag."""
    return _run(engine.cmd_read, query=query, project=project, agent=agent,
                tag=tag, limit=limit)


@mcp.tool()
def brain_dashboard() -> str:
    """Full situational awareness: active sessions, live file leases, recent handoffs,
    recent context notes, and vault health. Call at session start."""
    return _run(engine.cmd_dashboard)


if __name__ == "__main__":
    mcp.run(transport="stdio")
