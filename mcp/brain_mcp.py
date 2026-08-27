#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain_mcp.py - MCP bridge exposing the second-brain to any MCP client
(opencode, Hermes, Claude Code, Antigravity, Codex, ...).

Every tool wraps the deterministic engine (engine.py), so all agents
mutate one shared git-backed truth store + coordination layer.

Deterministic only: no LLM here. stdout stays clean for JSON-RPC; engine
prints are captured and returned as tool output.

Tools (16 total):
  Knowledge:  brain_status, brain_recall, brain_claim, brain_supersede,
              brain_dispute, brain_verify, brain_related, brain_sweep
  Coordination: brain_session_start, brain_session_update, brain_session_end,
                brain_sessions, brain_post, brain_read, brain_dashboard
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


# ================ KNOWLEDGE TOOLS ================

@mcp.tool()
def brain_status() -> str:
    """Vault health: claim counts, active sessions, context notes, chain
    integrity, L0 budget. Call to see overall brain state."""
    return _run(engine.cmd_status)


@mcp.tool()
def brain_recall(query: str = "", tag: str = "", status: str = "",
                 show_all: bool = False) -> str:
    """Deterministic recall over stored claims. Expired/superseded/disputed
    claims are withheld by default (show_all=True includes them, clearly marked).
    Call this before answering questions about the user's past work, preferences,
    or project facts — the vault is the shared memory across sessions/agents."""
    return _run(engine.cmd_recall, query=query, tag=tag, status=status,
                **{"all": show_all})


@mcp.tool()
def brain_claim(text: str, confidence: float = 0.9, source: str = "",
                tags: str = "", status: str = "active") -> str:
    """Record a claim (fact, preference, hard rule, outcome) into the shared
    brain. Git commit is made automatically (audit trail). Use source to name
    where the fact came from, tags for associative linking."""
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
    """Housekeeping: expire stale sessions (>24h), flag unreviewed claims,
    rebuild the L0 pointer set (sessions + context + claims, budget-aware).
    commit=True also makes a git commit."""
    return _run(engine.cmd_sweep, commit=commit)


# ================ COORDINATION TOOLS ================

@mcp.tool()
def brain_session_start(agent: str, project: str = "",
                        task: str = "") -> str:
    """Register this agent's active session. Call at the START of every
    conversation so other agents know what you're working on.
    Returns the session ID — save it for session_update/session_end calls."""
    return _run(engine.cmd_session_start, agent=agent, project=project,
                task=task)


@mcp.tool()
def brain_session_update(session_id: str, progress: str) -> str:
    """Append a progress milestone to your active session. Use for significant
    checkpoints (not every small step)."""
    return _run(engine.cmd_session_update, id=session_id, progress=progress)


@mcp.tool()
def brain_session_end(session_id: str, summary: str = "") -> str:
    """End your session. Record what you accomplished so the next agent
    picking up this project has context. Always call this when done."""
    return _run(engine.cmd_session_end, id=session_id, summary=summary)


@mcp.tool()
def brain_sessions(project: str = "", agent: str = "",
                   active_only: bool = True) -> str:
    """See what other agents are doing (or recently did). Call this at session
    start to check for conflicts or build on others' work."""
    return _run(engine.cmd_sessions, project=project, agent=agent,
                active=active_only)


@mcp.tool()
def brain_post(text: str, project: str = "", tags: str = "",
               agent: str = "") -> str:
    """Share a discovery, decision, or blocker with all agents. Lighter than
    brain_claim — use for session-scoped context that other agents should know.
    Use brain_claim for long-term facts instead."""
    return _run(engine.cmd_post, text=text, project=project, tags=tags,
                agent=agent)


@mcp.tool()
def brain_read(project: str = "", agent: str = "", tag: str = "",
               limit: int = 20) -> str:
    """Read context notes shared by other agents. Filter by project, agent,
    or tag. Use brain_recall for long-term knowledge instead."""
    return _run(engine.cmd_read, project=project, agent=agent, tag=tag,
                limit=limit)


@mcp.tool()
def brain_dashboard() -> str:
    """Full situational awareness: active sessions (who's doing what),
    recent context (shared discoveries), vault health. Call at the start
    of every session for multi-agent awareness."""
    return _run(engine.cmd_dashboard)


if __name__ == "__main__":
    mcp.run(transport="stdio")
