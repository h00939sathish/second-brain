#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain_mcp.py - MCP bridge exposing the second-brain L1 vault to any MCP client
(opencode, Hermes, Claude Code, ...).

Every tool wraps the deterministic engine (engine.py) in the same vault, so
CLI, opencode, and Hermes all mutate one shared git-backed truth store.

Deterministic only: no LLM here. stdout stays clean for JSON-RPC; engine
prints are captured and returned as tool output.
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
    """Run one engine command under the vault lock, returning its stdout."""
    args = SimpleNamespace(**kwargs)
    with engine.lock():
        cfg = engine.load_config()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = handler(args, cfg)
        out = buf.getvalue().strip()
    return out or f"(no output, exit {code})"


@mcp.tool()
def brain_status() -> str:
    """Vault health: claim counts by status, chain integrity, L0 budget.
    Use to see how full the brain is or whether the pointer set is over budget."""
    return _run(engine.cmd_status)


@mcp.tool()
def brain_recall(query: str = "", tag: str = "", status: str = "",
                 all_: bool = False) -> str:
    """Deterministic recall over stored claims. Expired/superseded/disputed
    claims are withheld by default (all_=True includes them, clearly marked).
    Call this before answering questions about the user's past work, preferences,
    or project facts - the vault is the shared memory across sessions/agents."""
    return _run(engine.cmd_recall, query=query, tag=tag, status=status, all=all_)


@mcp.tool()
def brain_claim(text: str, confidence: float = 0.9, source: str = "",
                tags: str = "", status: str = "active") -> str:
    """Record a claim (fact, preference, hard rule, outcome) into the shared
    brain. Git commit is made automatically (audit trail). Use --source to name
    where the fact came from, --tags for associative linking."""
    return _run(engine.cmd_claim, text=text, confidence=confidence,
                source=source, tags=tags, status=status)


@mcp.tool()
def brain_supersede(id: str, newid: str) -> str:
    """Mark claim <id> superseded by claim <newid> (chain-aware). Use when
    newer evidence replaces an older claim."""
    return _run(engine.cmd_supersede, id=id, newid=newid)


@mcp.tool()
def brain_dispute(id: str, reason: str = "", by: str = "") -> str:
    """Mark a claim disputed, keeping its evidence. Requires a reason."""
    return _run(engine.cmd_dispute, id=id, reason=reason, by=by)


@mcp.tool()
def brain_verify(id: str) -> str:
    """Chain-integrity check for one claim (dangling/cycle references)."""
    issues = engine.chain_issues(id, set())
    return "OK - chain clean" if not issues else "\n".join(issues)


@mcp.tool()
def brain_related(id: str) -> str:
    """Graph traversal: claims related to <id> via shared tags, wikilinks,
    or supersede edges."""
    return _run(engine.cmd_related, id=id)


@mcp.tool()
def brain_sweep(commit: bool = False) -> str:
    """Housekeeping: flag stale/unreviewed active claims, rebuild the L0
    pointer set (meta/l0_pointers.md). commit=True also makes a git commit."""
    return _run(engine.cmd_sweep, commit=commit)


if __name__ == "__main__":
    mcp.run(transport="stdio")
