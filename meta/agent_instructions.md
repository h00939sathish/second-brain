# Agent Integration Instructions

> Paste or inject this block into each agent's system prompt / instructions
> so they know how to use the shared brain. The L0 pointer set
> (`meta/l0_pointers.md`) auto-includes a condensed version of these
> instructions after each `sweep`.

## Second Brain (shared multi-agent memory)

You have access to a shared brain (MCP server: `second-brain`) that all
coding agents use. It has two layers:

**Knowledge** — long-term facts (claims with truth lifecycle):
- `brain_recall` — search stored facts/preferences/rules
- `brain_claim` — record a new fact (auto-committed to git)
- `brain_supersede` / `brain_dispute` — update truth state

**Coordination** — multi-agent awareness:
- `brain_dashboard` — full status: who's doing what, recent context, vault health
- `brain_session_start` — register your session (agent name, project, task)
- `brain_session_update` — log progress milestones
- `brain_session_end` — close session with summary of what you did
- `brain_sessions` — see other agents' active/recent sessions
- `brain_post` — share a discovery, decision, or blocker
- `brain_read` — read context notes from other agents

### Session protocol

At the **start** of every conversation:
1. Call `brain_dashboard` for situational awareness
2. Call `brain_session_start(agent="<your-name>", project="<project>", task="<what>")`
3. Save the returned session ID

**During** work:
- `brain_recall` for facts/knowledge before making assumptions
- `brain_read` for recent context from other agents
- `brain_post` to share important discoveries or decisions
- `brain_session_update` at significant milestones

At the **end** of your conversation:
- `brain_session_end(session_id, summary="what you accomplished")`

### What goes where

| Use case | Tool |
|---|---|
| Permanent fact, preference, rule | `brain_claim` |
| Session-scoped discovery, decision | `brain_post` |
| What am I working on right now | `brain_session_start` / `brain_session_update` |
| What did I accomplish | `brain_session_end` |

### Agent names (for --agent)

Use these consistent names across all sessions:
- `hermes` — Hermes agent
- `opencode` — opencode sessions
- `claude` — Claude Code
- `codex` — OpenAI Codex CLI
- `antigravity` — Google Antigravity (this IDE)
- (add more as needed)
