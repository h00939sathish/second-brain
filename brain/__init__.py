# -*- coding: utf-8 -*-
"""
Second Brain — shared memory, coordination and execution hub for coding agents.

Layout:
  L0  compact, always-injected pointers        (meta/l0_pointers.md)
  L1  this vault, git-backed markdown          (workspaces/<ws>/{claims,specs,tasks,sessions,context})
  L2  opaque agent transcripts                 (never read or written here)

Modules:
  const        tunables, agent specs, role map
  errors       typed failures (LeaseConflict, ReviewGate, SchemaError)
  paths        vault resolution, atomic writes, cross-platform advisory lock
  frontmatter  escaped YAML-ish frontmatter with guaranteed round-trip
  workspaces   workspace registry + cwd auto-detection
  index        incremental SQLite FTS5 index (BM25), actually used for reads
  vcs          scoped, checked git commits
  store        typed CRUD over claims/specs/tasks/sessions/context
  agents       agent CLI discovery + per-agent self-configuration
  dispatch     portable background dispatch of agent CLIs
  daemon       board watcher with heartbeat + circuit breaker
  l0           relevance-ranked pointer regeneration
  http         Mission Control API + universal /agent/bootstrap
  cli          argparse front-end
"""

__version__ = "5.0.0"
