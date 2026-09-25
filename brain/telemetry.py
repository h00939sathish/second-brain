# -*- coding: utf-8 -*-
"""Empirical capability telemetry and evidence-based task routing (Phase 5).

Projects observed worker performance from the immutable event stream, execution receipts,
and task completions. Replaces static agent stereotypes with empirical pass rates,
rework counts, and execution durations in your actual repositories.
"""

import math
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from . import board, const, events, evidence, store, workspaces as ws_mod


def _detect_domains(text: str = "", files: list = None) -> list:
    """Infer technical domains from file paths and prompt text."""
    domains = set()
    lowered = (text or "").lower()
    words = set(re.findall(r"[a-z0-9_+-]+", lowered))

    # Keyword patterns (whole-word matching)
    domain_keywords = {
        "python": {"python", "pytest", "py", "django", "flask", "fastapi"},
        "typescript": {"typescript", "javascript", "node", "npm", "react", "tsx", "ts", "js"},
        "shell": {"bash", "shell", "sh", "zsh", "script", "terminal"},
        "database": {"sql", "sqlite", "postgres", "database", "migration", "schema", "table"},
        "refactor": {"refactor", "cleanup", "restructure", "simplify", "reorganize"},
        "architecture": {"architecture", "design", "invariants", "spec", "protocol"},
        "test": {"test", "suite", "verify", "coverage", "mock"},
    }
    for domain, kws in domain_keywords.items():
        if words & kws:
            domains.add(domain)

    # File extensions
    for f in (files or []):
        f = str(f).lower()
        if f.endswith((".py", ".pyi")):
            domains.add("python")
        elif f.endswith((".ts", ".tsx", ".js", ".jsx")):
            domains.add("typescript")
        elif f.endswith((".sh", ".bash")):
            domains.add("shell")
        elif f.endswith((".sql", ".db")):
            domains.add("database")

    return sorted(domains) if domains else ["general"]


def compute_telemetry(workspace: str = "", all_workspaces: bool = True) -> Dict[str, dict]:
    """Project empirical agent telemetry from receipts, tasks, and event records."""
    slugs = ws_mod.all_slugs() if all_workspaces else [workspace or ws_mod.default_workspace()]

    # Agent -> domain -> stats
    agent_data = defaultdict(lambda: {
        "tasks_assigned": 0,
        "tasks_completed": 0,
        "runs_total": 0,
        "runs_passed": 0,
        "runs_failed": 0,
        "total_duration_ms": 0,
        "rework_count": 0,
        "domains": defaultdict(lambda: {"runs_total": 0, "runs_passed": 0}),
    })

    # Collect files from sessions linked to tasks
    task_files = defaultdict(list)
    for s in store.all_records("sessions", slugs):
        tid = s["fm"].get("task_id")
        if tid:
            for f in (s["fm"].get("files") or []):
                task_files[tid].append(f)

    # 1. Inspect tasks and their assignments
    all_tasks = store.all_records("tasks", slugs)
    task_map = {}
    for t in all_tasks:
        tid = t["id"]
        agent = board.resolve_agent(t["fm"].get("agent"))
        status = t["fm"].get("status")
        title = str(t["fm"].get("title") or "")
        files = list(t["fm"].get("files") or []) + task_files.get(tid, [])
        domains = _detect_domains(title, files)
        task_map[tid] = {"agent": agent, "status": status, "domains": domains}

        if agent:
            agent_data[agent]["tasks_assigned"] += 1
            if status == "done":
                agent_data[agent]["tasks_completed"] += 1

    # 2. Inspect execution receipts
    receipts_by_task = defaultdict(list)
    for slug in slugs:
        for r in evidence.get_receipts(workspace=slug, limit=1000):
            tid = r.get("task_id")
            if tid:
                receipts_by_task[tid].append(r)

    # Compute runs and first-pass rates per task
    for tid, tinfo in task_map.items():
        agent = tinfo["agent"]
        if not agent:
            continue
        rcpts = receipts_by_task.get(tid, [])
        if not rcpts:
            continue

        # Sort receipts by timestamp ascending
        rcpts.sort(key=lambda r: str(r.get("timestamp") or ""))

        # Check if rework occurred (failure followed by another run)
        had_failure = False
        task_domains = tinfo["domains"]

        for r in rcpts:
            exit_code = r.get("exit_code", -1)
            dur = r.get("duration_ms", 0)
            agent_data[agent]["runs_total"] += 1
            agent_data[agent]["total_duration_ms"] += dur

            for d in task_domains:
                agent_data[agent]["domains"][d]["runs_total"] += 1

            if exit_code == 0:
                agent_data[agent]["runs_passed"] += 1
                for d in task_domains:
                    agent_data[agent]["domains"][d]["runs_passed"] += 1
            else:
                agent_data[agent]["runs_failed"] += 1
                had_failure = True

        if had_failure and any(r.get("exit_code") == 0 for r in rcpts):
            agent_data[agent]["rework_count"] += 1

    # Compile final projection
    telemetry = {}
    for agent, stats in agent_data.items():
        runs = stats["runs_total"]
        passed = stats["runs_passed"]
        first_pass_rate = round(passed / runs, 2) if runs > 0 else 0.0
        avg_dur = int(stats["total_duration_ms"] / runs) if runs > 0 else 0

        # Domain breakdown
        domain_summary = {}
        for dom, dstats in stats["domains"].items():
            druns = dstats["runs_total"]
            dpass = dstats["runs_passed"]
            domain_summary[dom] = {
                "runs": druns,
                "pass_rate": round(dpass / druns, 2) if druns > 0 else 0.0,
            }

        telemetry[agent] = {
            "agent": agent,
            "role": board.role_of(agent),
            "tasks_assigned": stats["tasks_assigned"],
            "tasks_completed": stats["tasks_completed"],
            "runs_total": runs,
            "runs_passed": passed,
            "runs_failed": stats["runs_failed"],
            "first_pass_rate": first_pass_rate,
            "rework_count": stats["rework_count"],
            "avg_duration_ms": avg_dur,
            "domains": domain_summary,
        }

    return telemetry


def rank_agents(prompt: str = "", files: list = None, role: str = "builder",
                workspace: str = "", min_samples: int = 1) -> List[dict]:
    """Rank candidate agents for a task based on empirical evidence.

    Returns ranked list of agent recommendations with confidence scores.
    """
    telemetry = compute_telemetry(workspace=workspace, all_workspaces=True)
    domains = _detect_domains(prompt, files)

    # Candidate pool for the requested role
    candidates = [
        agent for agent, r in const.AGENT_ROLES.items()
        if r == role or (role == "builder" and r in ("builder", "operator"))
    ]

    rankings = []
    for agent in sorted(set(candidates)):
        stats = telemetry.get(agent, {
            "agent": agent,
            "role": board.role_of(agent),
            "tasks_assigned": 0,
            "tasks_completed": 0,
            "runs_total": 0,
            "runs_passed": 0,
            "first_pass_rate": 0.0,
            "rework_count": 0,
            "avg_duration_ms": 0,
            "domains": {},
        })

        runs = stats["runs_total"]
        completed = stats["tasks_completed"]
        first_pass = stats["first_pass_rate"]

        # Domain specific performance
        domain_rates = []
        for d in domains:
            dinfo = stats.get("domains", {}).get(d)
            if dinfo and dinfo["runs"] > 0:
                domain_rates.append(dinfo["pass_rate"])

        effective_pass_rate = (
            sum(domain_rates) / len(domain_rates)
            if domain_rates else first_pass
        )

        has_sufficient_data = runs >= min_samples
        if has_sufficient_data:
            # Empirical score: 60% pass rate + 25% completion volume + 15% domain relevance
            volume_bonus = min(completed / 5.0, 1.0) * 0.25
            score = round((effective_pass_rate * 0.60) + volume_bonus + (0.15 if domain_rates else 0.0), 3)
            confidence = "high" if runs >= 5 else "medium"
            reason = f"{int(effective_pass_rate * 100)}% pass rate across {runs} run(s) ({completed} tasks completed)"
            if domain_rates:
                reason += f" in domain(s): {', '.join(domains)}"
        else:
            # Prior based on role defaults
            score = 0.50
            confidence = "low"
            reason = f"prior default for {role} (insufficient empirical samples in repo)"

        rankings.append({
            "agent": agent,
            "role": stats["role"],
            "score": score,
            "confidence": confidence,
            "has_data": has_sufficient_data,
            "first_pass_rate": effective_pass_rate,
            "runs_total": runs,
            "tasks_completed": completed,
            "domains": domains,
            "reason": reason,
        })

    rankings.sort(key=lambda x: (x["has_data"], x["score"], x["runs_total"]), reverse=True)
    return rankings
