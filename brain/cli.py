# -*- coding: utf-8 -*-
"""`brain` command line.

Every command takes `-w/--workspace` and `--json`. With no `-w`, the workspace is
detected from the cwd (marker file, git config, then registered paths), which is what
makes the brain usable by an agent that has never been configured.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import (agents, attest, board, const, coordination, daemon, deliberation,
               dispatch, events, evidence, frontmatter, grants, goals, index, knowledge,
               l0, maintenance, messaging, seats, squad, store, telemetry, topology, tui,
               vcs, workspaces as ws_mod)
from .errors import BrainError, CycleDetectedError, DeliberationGate, DependencyBlockedError, LeaseConflict, NotFound, ReviewGate, TopologyError, UnverifiedEvidenceError
from .paths import VAULT, lock, stdout_utf8, time_ago

ROLE_HINT = {
    "planner": "draft invariants + split into cards (do not bulk-edit code)",
    "builder": "claim the card, lease files, implement, run tests, hand off to a reviewer",
    "reviewer": "audit the diff against the spec, run the suite, close the card",
    "orchestrator": "route cards to owners and keep the board honest",
}


# ---- output helpers ------------------------------------------------------


class Out:
    def __init__(self, as_json: bool = False):
        self.as_json = as_json
        self.lines = []

    def __call__(self, text: str = ""):
        if not self.as_json:
            print(text)

    def raw(self, text: str = ""):
        print(text)

    def payload(self, data, text: str = ""):
        if self.as_json:
            print(json.dumps(data, indent=2, default=str))
        elif text:
            print(text)
        return 0


def _agent(explicit: str = "") -> str:
    """Which seat this process is acting as.

    `--agent` *selects* an identity; it cannot *prove* one. Where the runtime already
    declared a seat for this process in $BRAIN_AGENT, a flag that disagrees is a
    forgery attempt and is refused. An empty $BRAIN_AGENT means the caller is not
    running under a seat at all, so the flag stands — and is recorded as unverified.
    """
    declared = board.resolve_agent(os.environ.get("BRAIN_AGENT") or "")
    wanted = board.resolve_agent(explicit)
    if declared and wanted and wanted != declared:
        raise BrainError(
            f"--agent {explicit!r} contradicts the seat this process declared "
            f"(BRAIN_AGENT={declared}). Speak as {declared}, or start a session as the "
            "seat you actually are: identity is not a flag to pick.")
    return declared or wanted or "unknown"


def _slug(args, cwd=None) -> str:
    return ws_mod.detect(cwd=cwd, explicit=getattr(args, "workspace", "") or "")


# ---- knowledge -----------------------------------------------------------


def cmd_init(args, out, cfg):
    from .paths import atomic_write, config_path, workspaces_path

    store.ensure_dirs()
    if not workspaces_path().exists():
        ws_mod.save_registry(ws_mod.load_registry(reload=True))
    ws_mod.ensure_all()
    gitignore = (
        "# brain state (never commit)\n"
        ".lock\n"
        "*.tmp\n"
        f"{const.WORKSPACE_MARKER}\n"
        "*.brainbak-*\n"
        f"{const.META_DIR}/{const.DB_NAME}*\n"
        f"{const.META_DIR}/{const.HEARTBEAT_NAME}\n"
        "*/logs/\n"
        "*.log\n"
    )
    ignore_path = VAULT / ".gitignore"
    existing = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    if "brain state" not in existing:
        atomic_write(ignore_path, (existing.rstrip() + "\n" + gitignore).lstrip("\n"))
    if not config_path().exists():
        store.save_config(store.config())
    if not vcs.is_repo():
        vcs._git(["init"])
    index.reindex_all()
    l0.write_all()
    return out.payload({"vault": str(VAULT), "workspaces": ws_mod.all_slugs()},
                       f"vault ready at {VAULT}\nworkspaces: {', '.join(ws_mod.all_slugs())}\n"
                       "next: brain setup   (configures every agent CLI it can find)")


def infer_workspace(fm: dict, body: str = "") -> str:
    """Best-guess workspace for a legacy record that has no `workspace` field.

    Legacy claims carry no project, so the signal has to come from what they say. Each
    registered workspace scores by how often its slug, name or aliases appear in the
    record's text; a tie or a zero match lands in the shared `global` workspace, which
    every workspace can read. `brain migrate --dry-run` prints every decision.
    """
    explicit = str(fm.get("project") or "").strip()
    if explicit:
        return ws_mod.resolve_alias(explicit)
    haystack = " ".join(str(v) for v in [fm.get("tags"), fm.get("source"),
                                        fm.get("claim"), body]).lower()
    best, best_score = const.GLOBAL_WORKSPACE, 0
    for slug in ws_mod.all_slugs():
        if slug == const.GLOBAL_WORKSPACE:
            continue
        info = ws_mod.entry(slug)
        needles = {slug.replace("-", " "), slug}
        needles.add(str(info.get("name", "")).lower())
        needles |= {str(a).lower() for a in (info.get("aliases") or [])}
        score = sum(1 for needle in needles if needle and needle in haystack)
        if score > best_score:
            best, best_score = slug, score
    return best


def cmd_migrate(args, out, cfg):
    """Move pre-workspace flat files into `workspaces/<slug>/` directories."""
    moved, applied = [], []
    legacy = {"claims": "claims", "specs": "specs", "tasks": "tasks",
              "sessions": "sessions", "context": "context"}
    for kind, dirname in legacy.items():
        source = VAULT / dirname
        if not source.is_dir():
            continue
        for path in sorted(source.glob(store.GLOBS[kind])):
            try:
                record = frontmatter.parse_file(path)
            except Exception:
                record = None
            if record is None:
                moved.append(f"SKIPPED {dirname}/{path.name} (unparseable)")
                continue
            slug = infer_workspace(record["fm"], record["body"])
            if not ws_mod.exists(slug):
                ws_mod.register(slug, description=f"auto-registered from {dirname}/")
            destination = ws_mod.subdir(slug, dirname) / path.name
            if destination.exists():
                moved.append(f"SKIPPED {dirname}/{path.name} (already in '{slug}')")
                continue
            if args.dry_run:
                moved.append(f"{dirname}/{path.name:<34} -> {slug}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.rename(destination)
            applied.append(f"{dirname}/{path.name:<34} -> {slug}")
            moved.append(f"{dirname}/{path.name:<34} -> {slug}")
    skipped = [m for m in moved if m.startswith("SKIPPED")]
    if args.dry_run:
        head = f"would migrate {len(moved) - len(skipped)} file(s)"
        if skipped:
            head += f", {len(skipped)} skipped (run `brain repair`)"
        return out.payload({"planned": moved},
                           head + "\n" + "\n".join(moved)
                           + "\n\nre-run without --dry-run to apply")
    index.reindex_all()
    l0.write_all()
    summary = f"migrated {len(applied)} file(s)"
    if skipped:
        summary += f", {len(skipped)} skipped (run `brain repair`)"
    return out.payload({"moved": applied, "skipped": skipped},
                       summary + "\nworkspaces: " + ", ".join(ws_mod.all_slugs()))


def cmd_claim(args, out, cfg):
    slug = _slug(args)
    result = knowledge.add(text=args.text, workspace=slug, status=args.status,
                          confidence=args.confidence, source=args.source, tags=args.tags,
                          scope="global" if args.global_scope else "",
                          verified_commit=getattr(args, "commit", "") or "",
                          depends_on=getattr(args, "depends_on", "") or "",
                          maturity=getattr(args, "maturity", "") or "")
    detail = f"claim {result['id']} [{result.get('maturity', 'provisional')}] written to workspace '{result['workspace']}' -> {result['path']}"
    if result.get("verified_commit"):
        detail += f" (commit: {result['verified_commit']})"
    return out.payload(result, detail)


def cmd_revalidate(args, out, cfg):
    result = knowledge.revalidate(args.id, workspace=_slug(args), note=args.note,
                                  verified_commit=getattr(args, "commit", "") or "")
    return out.payload(result, f"claim {result['id']} revalidated in '{result['workspace']}' (commit: {result['verified_commit']})")


def cmd_elevate(args, out, cfg):
    slug = _slug(args)
    maturity = getattr(args, "maturity", "canonical") or "canonical"
    result = knowledge.elevate(args.id, maturity=maturity, workspace=slug,
                               note=getattr(args, "note", "") or "")
    return out.payload(result, f"claim {result['id']} elevated to [{result['maturity']}] in '{result['workspace']}'")


def cmd_review(args, out, cfg):
    result = knowledge.review(args.id, workspace=_slug(args), note=args.note)
    return out.payload(result, f"claim {args.id} marked reviewed ({result['workspace']})")


def cmd_supersede(args, out, cfg):
    result = knowledge.supersede(args.id, args.newid)
    return out.payload(result, f"{args.id} superseded by {args.newid}")


def cmd_dispute(args, out, cfg):
    result = knowledge.dispute(args.id, reason=args.reason, by=args.by)
    return out.payload(result, f"{args.id} marked disputed")


def cmd_promote(args, out, cfg):
    result = knowledge.promote(args.id, workspace=_slug(args), confidence=args.confidence,
                              tags=args.tags)
    return out.payload(result, f"context note {args.id} promoted to claim {result['id']}")


def cmd_recall(args, out, cfg):
    slug = _slug(args)
    shown, withheld = knowledge.recall(
        query=args.query or "", workspace=slug, tag=args.tag or "", status=args.status or "",
        maturity=getattr(args, "maturity", "") or "",
        include_withheld=args.all, all_workspaces=args.all_workspaces, limit=args.limit or 0)
    if out.as_json:
        return out.payload({"workspace": slug, "matches": shown, "withheld": withheld})
    lines = [f"== RECALL '{args.query or ''}' in '{slug}' — {len(shown)} match(es), "
             f"{len(withheld)} withheld =="]
    for row in shown:
        lines.append(f"  [{row['status']}] [{row.get('maturity', 'provisional')}] {row['id']} ({row['workspace']})")
        lines.append(f"      {row['claim']}")
        if row["source"]:
            lines.append(f"      source: {row['source']}")
    if withheld:
        lines.append("-- WITHHELD (no longer current truth; --all to show) --")
        lines += [f"  [{r['status']}] [{r.get('maturity', 'provisional')}] {r['id']}  {r['claim']}" for r in withheld]
    return out.payload({"matches": shown, "withheld": withheld}, "\n".join(lines))


def cmd_related(args, out, cfg):
    rows = knowledge.related(args.id, workspace=_slug(args))
    if not rows:
        return out.payload([], f"no related claims to {args.id}") or 0
    lines = [f"== RELATED: {args.id} =="] + [
        f"  [[{r['id']}]] ({', '.join(r['reasons'])})\n      {r['claim'][:90]}" for r in rows]
    return out.payload(rows, "\n".join(lines))


def cmd_verify(args, out, cfg):
    if args.fix:
        targets = [args.id] if args.id else [
            row["id"] for row in store.all_records("claims")
            if knowledge.chain_issues(row["id"], workspace=row["workspace"])]
        cleared = []
        for target in targets:
            for link in knowledge.clear_dangling(target):
                cleared.append(f"{target}: cleared {link}")
        if cleared:
            index.sync(kinds=("claims",))
            l0.write_all()
        return out.payload({"cleared": cleared},
                           f"verify --fix: cleared {len(cleared)} dangling link(s)\n"
                           + "\n".join(f"  {c}" for c in cleared))

    problems = knowledge.verify(args.id or "", deep=True)
    pending = [] if args.id else knowledge.unreviewed(_slug(args), all_workspaces=True)
    lines = []
    if problems:
        lines.append(f"verify: {len(problems)} hard problem(s)")
        lines += [f"  {p}" for p in problems]
    else:
        lines.append("verify: clean — schema, chains and round-trips all OK")
    if pending:
        lines.append(f"\n{len(pending)} active claim(s) never reviewed (soft signal, not a "
                     "defect). Newest examples:")
        for row in pending[:5]:
            age = f"{row['age_days']}d" if row["age_days"] is not None else "?"
            lines.append(f"  {row['id']} ({row['workspace']}, {age}) {row['claim'][:70]}")
        lines.append("  stamp them with: brain review <id> --note 'checked <source>'")
    payload = {"ok": not problems, "problems": problems,
               "unreviewed": len(pending), "unreviewed_examples": pending[:5]}
    out.payload(payload, "\n".join(lines))
def cmd_verify_invariants(args, out, cfg):
    from . import invariants
    data = invariants.verify_all()
    lines = ["== CONSTITUTIONAL INVARIANTS =="]
    for inv in data["invariants"]:
        tag = f"[{inv['status']}]"
        lines.append(f"  {inv['id']}  {tag:<6}  {inv['title']} ({inv['test_count']} tests)")
    lines.append("-" * 40)
    lines.append(f"{data['passed']} / {data['total']} Constitutional Invariants Verified")
    out.payload(data, "\n".join(lines))
    return 0 if data["all_passed"] else 1


def cmd_status(args, out, cfg):
    slug = _slug(args)
    stats = knowledge.stats()
    board_data = board.board(workspace=slug, all_workspaces=args.all_workspaces)
    sessions = coordination.list_sessions(workspace=slug, active_only=True,
                                          all_workspaces=args.all_workspaces)
    locks = store.build_locks(ws_mod.read_scope(slug))
    dstatus = daemon.daemon_status()
    budget = l0.budget_state(slug)
    payload = {
        "vault": str(VAULT), "workspace": slug,
        "claims": stats, "board": board_data["counts"], "tasks_total": board_data["total"],
        "active_sessions": len(sessions), "file_locks": len(locks),
        "daemon": dstatus, "l0": budget,
        "workspaces": ws_mod.all_slugs(),
    }
    lines = [
        f"== SECOND BRAIN — workspace '{slug}' ==",
        f"vault: {VAULT}",
        f"claims: {stats['total']}  by status: {stats['by_status']}  "
        f"(shared/global: {stats['global']})",
        "board: " + " | ".join(f"{k}: {v}" for k, v in board_data["counts"].items()),
        f"sessions: {len(sessions)} active | file leases: {len(locks)}",
        f"daemon: {'running' if dstatus['active'] else 'stopped'} ({dstatus.get('detail', '')})",
        f"L0 brief: {budget['bytes']}B / {budget['budget']}B"
        + ("  OVER BUDGET" if budget["over"] else ""),
        f"workspaces: {', '.join(ws_mod.all_slugs())}",
    ]
    for path, info in locks.items():
        lines.append(f"  [LOCK] {path} -> {info['agent']} ({info['remaining_mins']}m left)")
    return out.payload(payload, "\n".join(lines))


def cmd_brief(args, out, cfg):
    slug = _slug(args)
    text = l0.render("" if slug == const.GLOBAL_WORKSPACE else slug)
    if args.write:
        l0.write_all()
    out.raw(text)
    return 0


def cmd_sweep(args, out, cfg):
    changed = maintenance.sweep(workspace=_slug(args), commit=args.commit)
    l0.write_all()
    return out.payload({"flagged": [{"id": i, "why": w} for i, w in changed]},
                       f"sweep: {len(changed)} item(s) processed")


# ---- workspaces ----------------------------------------------------------


def cmd_workspaces(args, out, cfg):
    action = args.action or "list"
    if action == "list":
        rows = []
        for slug in ws_mod.all_slugs():
            info = ws_mod.describe(explicit=slug)
            counts = {kind: len(list(ws_mod.subdir(slug, kind).glob(store.GLOBS[kind])))
                      for kind in store.KINDS if kind != "sessions"}
            sessions = len([s for s in store.all_records("sessions", [slug])
                            if s["fm"].get("status") == "active"])
            rows.append({**info, "counts": counts, "active_sessions": sessions})
        lines = ["== WORKSPACES =="]
        for row in rows:
            marker = "*" if row["is_default"] else " "
            lines.append(f" {marker} {row['slug']:<18} {row.get('path') or '(unbound)'}")
            lines.append(f"     {row.get('description', '')}")
            lines.append(f"     claims: {row['counts'].get('claims', 0)} | "
                         f"tasks: {row['counts'].get('tasks', 0)} | "
                         f"specs: {row['counts'].get('specs', 0)} | "
                         f"live sessions: {row['active_sessions']}")
        lines.append("  (* = default for unbound directories)")
        return out.payload(rows, "\n".join(lines))

    if action == "add":
        if not args.name:
            raise BrainError("workspace name required: brain workspaces add <name> [path]")
        slug = ws_mod.register(args.name, path=args.path or os.getcwd(),
                               description=args.description or "", make_default=args.default,
                               display_name=args.display_name, aliases=args.alias,
                               keywords=args.keywords)
        actions = ws_mod.bind_directory(slug, args.path or os.getcwd(),
                                        set_git_config=not args.no_git,
                                        pointer=getattr(args, "pointer", False),
                                        skill=getattr(args, "skill", False))
        return out.payload({"slug": slug, "actions": actions},
                           f"workspace '{slug}' registered\n" + "\n".join(f"  {a}" for a in actions))

    if action == "bind":
        slug = _slug(args) if args.workspace else ws_mod.detect(args.path or os.getcwd())
        if args.name:
            slug = ws_mod.resolve_alias(args.name)
        actions = ws_mod.bind_directory(slug, args.path or os.getcwd(),
                                        set_git_config=not args.no_git,
                                        pointer=getattr(args, "pointer", False),
                                        skill=getattr(args, "skill", False))
        return out.payload({"slug": slug, "actions": actions},
                           f"bound '{slug}'\n" + "\n".join(f"  {a}" for a in actions))

    if action == "default":
        if not args.name:
            raise BrainError("usage: brain workspaces default <name>")
        slug = ws_mod.register(args.name, make_default=True)
        return out.payload({"default": slug}, f"default workspace is now '{slug}'")

    if action == "remove":
        if not args.name:
            raise BrainError("usage: brain workspaces remove <name>")
        slug = ws_mod.unregister(args.name)
        return out.payload({"removed": slug}, f"workspace '{slug}' removed from the registry "
                                             "(its files were left on disk)")

    if action == "merge":
        if not args.name or not args.path:
            raise BrainError("usage: brain workspaces merge <from> <into>")
        try:
            target, moved = ws_mod.merge(args.name, args.path)
        except ValueError as exc:
            raise BrainError(str(exc))
        index.reindex_all()
        l0.write_all()
        return out.payload({"into": target, "moved": moved},
                           f"merged '{args.name}' into '{target}': {len(moved)} item(s)\n"
                           + "\n".join(f"  {m}" for m in moved))

    if action == "alias":
        if not args.name:
            raise BrainError("usage: brain workspaces alias <slug> [--display-name X] "
                             "[--alias Y]")
        result = ws_mod.set_identity(args.name, display_name=args.display_name,
                                     aliases=args.alias, keywords=args.keywords,
                                     replace=args.replace)
        return out.payload(result, f"workspace '{result['slug']}' identity: "
                                   f"{result['name']}\n  aliases:  "
                                   f"{', '.join(result['aliases'])}\n  keywords: "
                                   f"{', '.join(result.get('keywords', []))}")
    raise BrainError(f"unknown workspaces action {action!r}")


def cmd_ws(args, out, cfg):
    return cmd_workspaces(args, out, cfg)


def cmd_reclassify(args, out, cfg):
    """Move misfiled records into the workspace their content indicates."""
    source = args.workspace or const.GLOBAL_WORKSPACE
    moved, kept = knowledge.reclassify(source, dry_run=args.dry_run,
                                      all_workspaces=args.all_workspaces)
    if not args.dry_run and moved:
        index.reindex_all()
        l0.write_all()
    head = f"{'would move' if args.dry_run else 'moved'} {len(moved)} record(s), "
    head += f"left {kept} in '{source}'"
    lines = [head]
    for item in moved:
        lines.append(f"  {item['kind'][:4]}/{item['id']} {item['from']} -> {item['to']} "
                     f"(score {item['score']}) {item['claim']}")
    if args.dry_run and moved:
        lines.append("\nre-run without --dry-run to apply")
    out.payload({"moved": moved, "kept": kept}, "\n".join(lines))
    return 0


def cmd_repair(args, out, cfg):
    """Repair records whose frontmatter block lost its closing delimiter.

    Scans both the workspace directories and the legacy flat directories, so records
    can be repaired before or after migration.
    """
    fixed, failed, clean = [], [], 0
    candidates = []
    for kind in store.KINDS:
        legacy = VAULT / store.DIRS[kind]
        if legacy.is_dir():
            candidates += [(kind, f"legacy/{kind}", p)
                           for p in sorted(legacy.glob(store.GLOBS[kind]))]
        for slug in ws_mod.all_slugs():
            directory = ws_mod.subdir(slug, kind)
            if directory.is_dir():
                candidates += [(kind, slug, p)
                               for p in sorted(directory.glob(store.GLOBS[kind]))]
    for kind, label, path in candidates:
        try:
            frontmatter.parse_file(path)
        except (BrainError, OSError):
            ok, detail = store.repair_malformed(path, kind=kind, dry_run=args.dry_run)
            (fixed if ok else failed).append(f"{label}/{path.name}: {detail}")
            continue
        clean += 1
    lines = [f"repair: {len(fixed)} file(s) {'to fix' if args.dry_run else 'fixed'}, "
             f"{len(failed)} unfixable, {clean} already clean"]
    lines += [f"  OK   {f}" for f in fixed] + [f"  FAIL {f}" for f in failed]
    if not args.dry_run and fixed:
        index.reindex_all()
    out.payload({"fixed": fixed, "failed": failed, "clean": clean}, "\n".join(lines))
    return 0 if not failed else 1


# ---- board ---------------------------------------------------------------


def cmd_goal_propose(args, out, cfg):
    goal = getattr(args, "goal", "") or ""
    tasks = []
    spec = None
    if getattr(args, "file", None):
        p = Path(args.file)
        if not p.is_file():
            raise NotFound(f"proposal file not found: {args.file}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            goal = goal or data.get("goal", "")
            tasks = data.get("tasks", [])
            spec = data.get("spec")
        elif isinstance(data, list):
            tasks = data
    if getattr(args, "tasks_json", None):
        tasks = json.loads(args.tasks_json)

    if getattr(args, "spec_title", None) or getattr(args, "spec_desc", None):
        spec = spec or {}
        if getattr(args, "spec_title", None):
            spec["title"] = args.spec_title
        if getattr(args, "spec_desc", None):
            spec["description"] = args.spec_desc

    result = goals.propose_goal(
        goal=goal,
        tasks=tasks,
        spec=spec,
        workspace=_slug(args),
        project=getattr(args, "project", "") or "",
        actor=getattr(args, "actor", "") or "agent:jarvis",
    )
    lines = [
        "== GOAL PROPOSAL AUTHORIZED ==",
        f"  Goal: {result['goal']}",
        f"  Workspace: {result['workspace']}",
    ]
    if result.get("spec_id"):
        lines.append(f"  Spec ID: {result['spec_id']}")
    lines.append(f"  Created Tasks ({len(result['tasks'])}):")
    for t in result["tasks"]:
        dep_str = f" [depends on: {', '.join(t['depends_on'])}]" if t.get("depends_on") else ""
        lines.append(f"    - {t['id']} ({t['key']}): {t['title']} [{t['status']}]{dep_str}")
    return out.payload(result, "\n".join(lines))


def cmd_spec_create(args, out, cfg):
    result = board.create_spec(title=args.title, spec=args.spec, workspace=_slug(args),
                              project=args.project, phases=args.phases)
    return out.payload(result, f"spec {result['id']} created in '{result['workspace']}'")


def cmd_specs(args, out, cfg):
    specs = board.list_specs(workspace=_slug(args), project=args.project or "",
                             all_workspaces=args.all_workspaces)
    rows = [{"id": s["id"], "title": s["fm"].get("title"), "project": s["fm"].get("project"),
             "workspace": s["workspace"], "phases": s["fm"].get("phases"),
             "age": time_ago(s["fm"].get("created"))} for s in specs]
    lines = [f"== SPECS ({len(rows)}) =="]
    for row in rows:
        lines.append(f"  {row['id']} ({row['workspace']}) {row['title']} [{row['age']}]")
        if row["phases"]:
            phases = row["phases"] if isinstance(row["phases"], list) else [row["phases"]]
            lines.append("      phases: " + " | ".join(str(p) for p in phases))
    return out.payload(rows, "\n".join(lines))


def cmd_task_create(args, out, cfg):
    result = board.create_task(title=args.title, workspace=_slug(args), project=args.project,
                              spec_id=args.spec, agent=args.agent, phase=args.phase,
                              files=args.files, status=getattr(args, "status", "") or "",
                              depends_on=getattr(args, "depends_on", "") or "",
                              coordination_required=bool(getattr(args, "coordination_required", False)))
    detail = f"task {result['id']} created in [{result['workspace']}] [{result['status']}]"
    if result.get("depends_on"):
        detail += f" (depends on: {', '.join(result['depends_on'])})"
    return out.payload(result, detail)


def cmd_deliberate(args, out, cfg):
    # Common flags parsed by parent: "w", "h", "help"
    action = getattr(args, "action", "") or "status"
    task_id = getattr(args, "task", "") or getattr(args, "id", "")
    if not task_id:
        raise BrainError("a task ID is required for deliberation")
    slug = _slug(args)

    if action in ("open", "post", "propose", "object", "resolve", "presence", "adjudicate"):
        caller = board.resolve_agent(os.environ.get("BRAIN_AGENT", "").strip())
        if not caller:
            raise BrainError(
                "no $BRAIN_AGENT in this process: there is no seat to attribute this to, "
                "and every agent on this host shares one unix user. Set BRAIN_AGENT=<seat> — "
                "failing closed, not guessing."
            )
        actor_flag = getattr(args, "agent", "") or getattr(args, "sender", "") or getattr(args, "actor", "")
        claimed = board.resolve_agent(actor_flag)
        if claimed and claimed != caller and caller != "operator":
            events.emit("MESSAGE_FORGERY_REFUSED", stage="AUTHORIZE", workspace=slug,
                        actor=f"agent:{caller}", task_id=task_id,
                        payload={"reason": f"{caller} cannot act as {claimed!r}",
                                 "claimed_sender": claimed, "to": "room"})
            raise BrainError(f"{caller} cannot act as {claimed!r}: the sender is the seat this process runs as ($BRAIN_AGENT)")
        effective_agent = caller if caller != "operator" and not claimed else (claimed or caller)
    else:
        effective_agent = "operator"

    if action == "open":
        participants = [p.strip() for p in (getattr(args, "participants", "") or "").split(",") if p.strip()] or None
        domains = [d.strip() for d in (getattr(args, "domains", "") or "").split(",") if d.strip()] or None
        res = deliberation.open_room(
            task_id=task_id,
            workspace=slug,
            risk=getattr(args, "risk", "normal") or "normal",
            mode=getattr(args, "mode", "normal") or "normal",
            participants=participants,
            domains=domains,
            max_rounds=getattr(args, "max_rounds", 3) or 3,
            actor=effective_agent,
        )
        msg = f"Deliberation Room opened for {task_id} [{res['risk']} risk, {res['mode']} mode]\n  Participants: {', '.join(res['required_participants'])}"
        return out.payload(res, msg)

    if action == "post":
        refs = [r.strip() for r in (getattr(args, "ref", "") or "").split(",") if r.strip()] or None
        res = deliberation.post_message(
            task_id=task_id,
            sender=effective_agent,
            msg_type=getattr(args, "type", "SUGGESTION") or "SUGGESTION",
            body=getattr(args, "body", "") or "",
            recipient=getattr(args, "recipient", "") or "",
            severity=getattr(args, "severity", "medium") or "medium",
            references=refs,
            workspace=slug,
        )
        return out.payload(res, f"[{res['type']}] ({res['sender']}): {res['body'][:80]}")

    if action == "propose":
        plan = [p.strip() for p in (getattr(args, "plan", "") or "").split(";") if p.strip()] or [getattr(args, "plan", "")]
        files = [f.strip() for f in (getattr(args, "files", "") or "").split(",") if f.strip()] or None
        risks = [r.strip() for r in (getattr(args, "risks", "") or "").split(";") if r.strip()] or None
        res = deliberation.submit_proposal(
            task_id=task_id,
            agent=effective_agent,
            plan=plan,
            files_expected=files,
            risks=risks,
            workspace=slug,
        )
        return out.payload(res, f"Proposal {res['proposal_id']} submitted by {res['agent']} ({len(res['plan'])} step(s))")

    if action == "object":
        refs = [r.strip() for r in (getattr(args, "ref", "") or "").split(",") if r.strip()] or None
        res = deliberation.raise_objection(
            task_id=task_id,
            sender=effective_agent,
            body=getattr(args, "body", "") or "",
            proposal_id=getattr(args, "prop_id", "") or "",
            severity=getattr(args, "severity", "high") or "high",
            references=refs,
            workspace=slug,
        )
        return out.payload(res, f"OBJECTION raised by {res['sender']} [{res['severity']}]: {res['body'][:80]}")

    if action == "resolve":
        res = deliberation.resolve_objection(
            task_id=task_id,
            resolver=effective_agent,
            message_id_or_ref=getattr(args, "ref", "") or "",
            resolution_notes=getattr(args, "notes", "") or "",
            workspace=slug,
        )
        return out.payload(res, f"Objection {getattr(args, 'ref', '')} resolved: {getattr(args, 'notes', '')[:80]}")

    if action == "presence":
        files = [f.strip() for f in (getattr(args, "files", "") or "").split(",") if f.strip()] or None
        res = deliberation.update_presence(
            task_id=task_id,
            agent=effective_agent,
            state=getattr(args, "state", "ANALYZING") or "ANALYZING",
            focus=getattr(args, "focus", "") or "",
            files=files,
            workspace=slug,
        )
        return out.payload(res, f"Presence updated: {res['agent']} [{res['state']}] - {res['focus']}")

    if action == "adjudicate":
        res = deliberation.adjudicate(
            task_id=task_id,
            workspace=slug,
            actor=effective_agent,
        )
        if res.get("ok"):
            lines = [
                f"== DELIBERATION ADJUDICATION: AUTHORIZED ==",
                f"  Task: {task_id}",
                f"  Participants: {', '.join(res['decision']['participants'])}",
                f"  Authorized Files: {', '.join(res['decision']['authorized_files'])}",
                f"  Agreed Steps ({len(res['decision']['agreed_plan'])}):",
            ]
            for step in res['decision']['agreed_plan']:
                lines.append(f"    - {step}")
            return out.payload(res, "\n".join(lines))
        else:
            lines = [
                f"== DELIBERATION ADJUDICATION: BLOCKED ==",
                f"  Task: {task_id}",
                f"  Reason: {res.get('reason')}",
            ]
            if res.get("unresolved_objections"):
                lines.append("  Unresolved Objections:")
                for u in res["unresolved_objections"]:
                    lines.append(f"    - [{u['severity']}] {u['sender']}: {u['body']}")
            return out.payload(res, "\n".join(lines))

    # default: status
    room = deliberation.get_room(task_id, slug)
    ctx = room["context"]
    lines = [
        f"== DELIBERATION ROOM: {task_id} ==",
        f"  Title: {ctx.get('title')}",
        f"  Status: {ctx.get('status')} | Round: {ctx.get('current_round')}/{ctx.get('max_rounds')} | Risk: {ctx.get('risk')}",
        f"  Required Participants: {', '.join(ctx.get('required_participants', []))}",
    ]
    if room["presence"]:
        lines.append("  Agent Presence:")
        for agent, p in room["presence"].items():
            f_str = f" touching {', '.join(p['files'])}" if p.get("files") else ""
            lines.append(f"    - {agent}: [{p['state']}] {p.get('focus', '')}{f_str}")
    if room["proposals"]:
        lines.append(f"  Proposals ({len(room['proposals'])}):")
        for prop in room["proposals"]:
            lines.append(f"    - {prop['proposal_id']} ({prop['agent']}) [{prop['status']}]: {'; '.join(prop['plan'][:2])}")
    if room["messages"]:
        lines.append(f"  Recent Messages ({len(room['messages'])}):")
        for m in room["messages"][-5:]:
            lines.append(f"    [{m['type']}] {m['sender']}: {m['body'][:80]}")
    if room["decision"]:
        lines.append(f"  Decision Record: [{room['decision']['status']}] by {room['decision']['adjudicator']}")
    return out.payload(room, "\n".join(lines))


def cmd_who_working(args, out, cfg):
    task_id = getattr(args, "task", "") or ""
    slug = _slug(args)
    if task_id:
        if deliberation.has_room(task_id, slug):
            room = deliberation.get_room(task_id, slug)
            presence = room.get("presence", {})
            if out.as_json:
                return out.payload(presence)
            lines = [f"== AGENT PRESENCE FOR {task_id} =="]
            if not presence:
                lines.append("  (no active presence reported)")
            for agent, p in presence.items():
                f_str = f" files: {', '.join(p['files'])}" if p.get("files") else ""
                lines.append(f"  {agent}: [{p['state']}] focus: {p.get('focus', 'none')}{f_str}")
            return out.payload(presence, "\n".join(lines))
    # Fallback to active sessions
    sessions = coordination.list_sessions(workspace=slug, active_only=True)
    if out.as_json:
        return out.payload(sessions)
    lines = [f"== ACTIVE AGENTS ({len(sessions)}) =="]
    for s in sessions:
        fm = s["fm"]
        files = fm.get("files") or []
        f_str = f" leasing: {', '.join(files)}" if files else ""
        lines.append(f"  {fm.get('agent')}: task {fm.get('task_id', 'unassigned')} ({fm.get('task', '')}){f_str}")
    return out.payload(sessions, "\n".join(lines))


def cmd_room(args, out, cfg):
    return cmd_deliberate(args, out, cfg)


def cmd_move(args, out, cfg):
    closure_reason = getattr(args, "closure", "") or ""
    closure_target = getattr(args, "closure_target", "") or ""
    result = board.move(args.id, args.status, workspace=_slug(args), agent=args.agent,
                        notes=args.notes, force=args.force, tests=args.tests,
                        closure_reason=closure_reason, closure_target=closure_target)
    if not result.get("changed"):
        return out.payload(result, f"task {args.id} already in [{args.status}]")
    message = f"task {args.id}: {result['from']} -> {result['status']}"
    if result.get("detail"):
        message += f"\n  {result['detail']}"
    return out.payload(result, message)


def cmd_tasks(args, out, cfg):
    slug = _slug(args)
    tasks = board.list_tasks(workspace=slug, project=args.project or "", status=args.status or "",
                            agent=args.agent or "", all_workspaces=args.all_workspaces)
    counts = {status: 0 for status in const.TASK_STATUSES}
    for task in tasks:
        counts[str(task["fm"].get("status") or "backlog")] = \
            counts.get(str(task["fm"].get("status") or "backlog"), 0) + 1
    if out.as_json:
        return out.payload([{"id": t["id"], "title": t["fm"].get("title"),
                             "status": t["fm"].get("status"), "agent": t["fm"].get("agent"),
                             "workspace": t["workspace"], "spec": t["fm"].get("spec_id")}
                            for t in tasks])
    lines = [f"== BOARD in '{slug}' — {len(tasks)} card(s) =="]
    for status in const.TASK_STATUSES:
        group = [t for t in tasks if str(t["fm"].get("status")) == status]
        lines.append(f"\n--- {status.upper()} ({len(group)}) ---")
        if not group:
            lines.append("  (empty)")
        for task in group:
            fm = task["fm"]
            owner = f" [{board.resolve_agent(fm.get('agent')) or 'unassigned'}]"
            spec = f" spec:[[{fm.get('spec_id')}]]" if fm.get("spec_id") else ""
            lines.append(f"  * {task['id']}{owner} {fm.get('title')}{spec}")
    return out.payload({"counts": counts}, "\n".join(lines))


def cmd_route(args, out, cfg):
    slug = _slug(args)
    result = board.route(args.agent, args.prompt, workspace=slug, project=args.project or "",
                         cfg=cfg)
    if out.as_json:
        return out.payload(result)
    return out.payload(result, f"route: {result['action']} (score {result['score']}) "
                               f"— agent {result['agent']}, role {result['role']}\n"
                               + (f"signals: {', '.join(result['signals'])}\n"
                                  if result["signals"] else "")
                               + "\n" + result["brief"])


def cmd_next(args, out, cfg):
    result = board.next_action(args.agent, workspace=_slug(args), project=args.project or "")
    return out.payload(result, result["brief"])


def cmd_squad(args, out, cfg):
    action = getattr(args, "action", "") or "show"
    slug = _slug(args)
    if action == "init":
        name = getattr(args, "name", "") or f"{slug}-squad"
        res = squad.save_squad({"name": name, "roles": dict(const.DEFAULT_SQUAD_ROLES)}, workspace=slug)
        return out.payload(res, f"initialized squad '{res['name']}' at {res['path']}")
    if action == "set":
        role = getattr(args, "role", "") or ""
        agent = getattr(args, "agent", "") or ""
        if not role or not agent:
            raise BrainError("usage: brain squad set <role> <agent>")
        res = squad.set_role(role, agent, workspace=slug)
        return out.payload(res, f"role '{role}' set to '{agent}' in squad '{res['name']}'")
    # default: show
    res = squad.squad_status(slug)
    if out.as_json:
        return out.payload(res)
    configured_str = "declared" if res["configured"] else "default (unconfigured)"
    lines = [f"== SQUAD '{res['name']}' in '{slug}' [{configured_str}] =="]
    for m in res["members"]:
        status_str = "[IDLE]"
        detail = ""
        if m["active"]:
            s = m["session"]
            status_str = "[ACTIVE]"
            files_str = f" leasing: {', '.join(s['files'])}" if s.get("files") else ""
            detail = f" -> task {s.get('task_id') or 'none'} ({s.get('task')}){files_str}"
        lines.append(f"  {m['role']:<10} : {m['agent']:<12} {status_str}{detail}")
    return out.payload(res, "\n".join(lines))


def cmd_tui(args, out, cfg):
    slug = _slug(args)
    once = getattr(args, "once", False)
    interval = getattr(args, "interval", 2.0) or 2.0
    if once or not sys.stdout.isatty():
        state = tui.collect_state(slug)
        snapshot = tui.render_snapshot(state)
        return out.raw(snapshot) or 0
    try:
        import curses
        curses.wrapper(tui.run_curses, workspace=slug, interval=interval)
        return 0
    except Exception:
        state = tui.collect_state(slug)
        snapshot = tui.render_snapshot(state)
        return out.raw(snapshot) or 0


# ---- coordination --------------------------------------------------------


def cmd_start(args, out, cfg):
    slug = _slug(args)
    agent = _agent(args.agent)
    result = coordination.start(agent=agent, workspace=slug, project=args.project or "",
                               task=args.task or "", task_id=args.task_id or "",
                               files=args.files or "", branch=args.branch or "",
                               worktree=args.worktree or "", lease_mins=args.lease,
                               force=args.force, cfg=cfg)
    lines = [f"session {result['id']} open for {agent} in '{result['workspace']}'",
             f"  project: {args.project or args.task_id or '(unscoped)'}"]
    if result["files"]:
        lines.append(f"  leases: {', '.join(result['files'])} until {result['lease_expires']}")
        lines.append("  other agents are now refused on those paths")
    lines.append(f"  end it with: brain end {result['id']} --summary '...' --test-status '...'")
    return out.payload(result, "\n".join(lines))


def cmd_update(args, out, cfg):
    result = coordination.update(args.id, progress=args.progress or "", files=args.files or "",
                                extend_lease=args.extend_lease, workspace=_slug(args))
    return out.payload(result, f"session {args.id} updated")


def cmd_reserve(args, out, cfg):
    result = coordination.reserve(args.id, args.files, lease_mins=args.lease,
                                 workspace=_slug(args), force=args.force, cfg=cfg)
    return out.payload(result, f"reserved {', '.join(result['files'])} until "
                               f"{result['lease_expires']}")


def cmd_check_files(args, out, cfg):
    conflicts = coordination.check_files(args.files, workspace=_slug(args))
    if not conflicts:
        out.payload({"ok": True, "files": args.files},
                    f"OK — no leases on {len(args.files.split(','))} file(s)")
        return 0
    lines = [f"REFUSED — {len(conflicts)} file(s) are leased by another live session:"]
    for target, info in conflicts:
        lines.append(f"  {target} -> {info['agent']} (session {info['session_id']}, "
                     f"{info['remaining_mins']}m left)")
    lines.append("Wait, coordinate with the holder, or pass --force if you are sure.")
    out.payload({"ok": False, "conflicts": [{"file": f, **i} for f, i in conflicts]},
                "\n".join(lines))
    return 1


def cmd_end(args, out, cfg):
    closure_reason = getattr(args, "closure", "") or ""
    closure_target = getattr(args, "closure_target", "") or ""
    result = coordination.end(args.id, summary=args.summary or "",
                             target_agent=args.target_agent or "",
                             next_steps=args.next_steps or "",
                             modified_files=args.modified_files or "",
                             test_status=args.test_status or "", workspace=_slug(args),
                             closure_reason=closure_reason, closure_target=closure_target)
    lines = [f"session {args.id} ended, leases released"]
    if args.target_agent:
        lines.append(f"  handed off to {board.resolve_agent(args.target_agent)}")
    if args.test_status:
        lines.append(f"  tests: {args.test_status}")
    if closure_reason:
        lines.append(f"  closure: {closure_reason}")
    return out.payload(result, "\n".join(lines))


def cmd_sessions(args, out, cfg):
    slug = _slug(args)
    sessions = coordination.list_sessions(agent=args.agent or "", workspace=slug,
                                         project=args.project or "",
                                         active_only=args.active,
                                         all_workspaces=args.all_workspaces)
    if out.as_json:
        return out.payload([{"id": s["id"], "agent": s["fm"].get("agent"),
                             "status": s["fm"].get("status"), "task_id": s["fm"].get("task_id"),
                             "files": s["fm"].get("files"), "workspace": s["workspace"],
                             "started": s["fm"].get("started"),
                             "target_agent": s["fm"].get("target_agent"),
                             "test_status": s["fm"].get("test_status")} for s in sessions])
    lines = [f"== SESSIONS in '{slug}' ({len(sessions)}) =="]
    for session in sessions:
        fm = session["fm"]
        status = str(fm.get("status"))
        active = "active" in status
        marker = "*" if active else "."
        lines.append(f"  {marker} [{status}] {fm.get('agent')} -> {fm.get('project') or 'unscoped'}"
                     f"{' [' + str(fm.get('branch')) + ']' if fm.get('branch') else ''}: "
                     f"{fm.get('task') or fm.get('task_id') or ''} "
                     f"({time_ago(fm.get('started'))})")
        if active and fm.get("files"):
            lines.append(f"      leases: {', '.join(_files(fm.get('files')))}")
        if fm.get("target_agent"):
            lines.append(f"      handoff -> {fm.get('target_agent')}")
        if fm.get("test_status"):
            lines.append(f"      tests: {fm.get('test_status')}")
        lines.append(f"      id: {session['id']}")
    return out.payload({"sessions": len(sessions)}, "\n".join(lines))


def cmd_events(args, out, cfg):
    slug = _slug(args)
    records = events.read_events(
        workspace=slug,
        date=args.date or "",
        event_type=args.type or "",
        task_id=args.task or "",
        stage=args.stage or "",
        actor=args.actor or "",
        limit=int(args.limit or 50),
        reverse=not args.oldest,
        all_workspaces=args.all_workspaces,
    )
    if out.as_json:
        return out.payload(records)
    if not records:
        return out.payload([], "No events matching query.")
    lines = [f"== EVENTS ({len(records)}) =="]
    for ev in records:
        ts = ev.get("timestamp", "")[:19]
        seq = ev.get("sequence", 0)
        etype = ev.get("event_type", "")
        actor = ev.get("actor", "")
        task = ev.get("task_id", "")
        stage = ev.get("stage", "")
        ws = ev.get("workspace", "")
        extra = f" task={task}" if task else ""
        if args.all_workspaces:
            extra += f" ws={ws}"
        lines.append(f"  [{ts} #{seq:04d}] {stage:<9} {etype:<18} actor={actor}{extra}")
    return out.payload(records, "\n".join(lines))


def cmd_record_evidence(args, out, cfg):
    """Tripwire: an agent must never be able to declare its own exit code.

    Kept as a command rather than deleted so the attempt is answered with an explanation
    and written to the audit stream instead of surfacing as an argparse error.
    """
    slug = _slug(args)
    events.emit("EVIDENCE_FORGERY_REFUSED", stage="AUTHORIZE", workspace=slug,
                task_id=args.task, actor=f"agent:{_agent(getattr(args, 'agent', ''))}",
                payload={"claimed_exit_code": args.exit_code, "command": args.cmd_text})
    raise UnverifiedEvidenceError(
        "brain no longer accepts asserted execution results: an exit code you type is a "
        "claim, not evidence. Run the command and let the runtime observe it: "
        "`brain test --task <id> --cmd-text \"pytest -q\"`"
    )


def cmd_attest(args, out, cfg):
    status = attest.status()
    status["witness"] = {
        "binary": const.WITNESS_BINARY,
        "installed": os.path.isfile(const.WITNESS_BINARY),
        "reachable_without_password": evidence.witness_available(),
    }
    if out.as_json:
        return out.payload(status)
    lines = [
        "== ATTESTATION =="  ,
        f"  mode:        {status['mode']}",
        f"  boundary:    {status['boundary']}",
        f"  key:         {status['key_fingerprint'] or '(none)'} @ {status['public_key']}",
        f"  trust root:  {status['trust_root']}",
        f"  witness:     {status['witness']['binary']} "
        f"({'present' if status['witness']['installed'] else 'MISSING'})",
        f"  signer:      {'available' if status['signer_available'] else 'requires sudo -n brain-witness'}",
    ]
    if status["mode"] == "bootstrap":
        lines.append("  WARNING: no root-owned trust anchor. Agents can mint their own key, "
                     "so evidence is signed but not unforgeable. Install trust to close this.")
    return out.payload(status, "\n".join(lines))


def cmd_grants(args, out, cfg):
    rows = grants.list_grants()
    payload = {"trust_mode": attest.mode(), "grants": rows}
    lines = [f"== BYPASS GRANTS == ({attest.mode()})"]
    if not rows:
        lines.append("  none unspent. Mint one as the operator:\n"
                     f"    sudo {const.WITNESS_BINARY} grant-bypass --seat <seat> "
                     "--reason \"why\" --minutes 30")
    for grant in rows:
        flag = "EXPIRED" if grant["expired"] else str(grant["attestation"]).upper()
        lines.append(f"  {grant['grant_id']}  seat={grant['seat']}  {flag}  "
                     f"until {grant['expires']}")
        lines.append(f"    reason: {grant['reason']}")
    return out.payload(payload, "\n".join(lines))


def cmd_bypass_grant(args, out, cfg):
    """Ask the privileged witness for a grant. It demands a password, so an agent that
    runs this command is refused — which is the point of the whole exercise."""
    seat = args.seat or os.environ.get("BRAIN_AGENT", "").strip()
    if not seat:
        raise BrainError("name the seat this grant covers with --seat (or set BRAIN_AGENT)")
    if not os.path.isfile(const.WITNESS_BINARY):
        raise BrainError(
            f"no witness at {const.WITNESS_BINARY}. Until trust is installed there is no "
            "human-authorised bypass: BRAIN_BYPASS=1 works but is self-granted and is "
            "written to the event stream as such.")
    call = ["sudo", const.WITNESS_BINARY, "grant-bypass", "--seat", seat,
            "--reason", args.reason, "--minutes", str(args.minutes), "--vault", str(VAULT)]
    res = subprocess.run(call, capture_output=True, text=True)
    token = (res.stdout or "").strip()
    if res.returncode != 0 or not token:
        detail = (res.stderr or res.stdout or "").strip() or f"exit {res.returncode}"
        raise BrainError(f"witness refused: {detail}")
    payload = {"token": token, "seat": seat, "env": grants.TOKEN_ENV}
    return out.payload(payload, "\n".join([
        (res.stderr or "").strip(),
        f"  carry it with:  export {grants.TOKEN_ENV}={token}",
        "  one use, bound to this seat, then spent — it buys one step over the line."]))


def cmd_verify_boundary(args, out, cfg):
    """Run the adversarial tier: the number the unit suite cannot tell you.

    A green unit suite means the code does what it says when used honestly. This asks
    whether a dishonest agent inside the trust domain can defeat it.
    """
    suite = VAULT / "tests" / "hostile"
    if not suite.is_dir():
        raise BrainError(f"no hostile probe suite at {suite}")
    res = subprocess.run([sys.executable, str(VAULT / "tools" / "hostile_report.py"),
                          str(VAULT)], capture_output=True, text=True, cwd=str(VAULT))
    try:
        report = json.loads(res.stdout)
    except (json.JSONDecodeError, ValueError):
        raise BrainError(f"hostile report failed: {(res.stderr or res.stdout).strip()[-400:]}")
    verdicts = report["verdicts"]
    lines = ["== TRUST BOUNDARY (adversarial tier) ==",
             f"  {report['blocked']}/{report['probes']} probes blocked"
             + (f", {report['known_open']} known-open" if report["known_open"] else "")
             + (f", {report['broken']} REGRESSIONS" if report["broken"] else "")
             + (f", {report['skipped']} skipped" if report["skipped"] else "")]
    for name in sorted(verdicts):
        state = verdicts[name]
        if state != "blocked":
            lines.append(f"  {state:<8} {name}")
    for name, buckets in sorted(report["detail"].items()):
        lines.extend(f"            {name}: {test}" for test in buckets["broken"])
    if report["unexpected_successes"]:
        lines.append("  now closed (drop the expectedFailure marker):")
        lines.extend(f"    {test}" for test in report["unexpected_successes"])
    lines.append("\n  (the unit suite answers a different question: this one is answered "
                 "only by attacking the boundary)")
    out.payload(report, "\n".join(lines))
    return 0 if res.returncode == 0 else 1


def cmd_test(args, out, cfg):
    slug = _slug(args)
    session_id = args.session or ""
    if evidence.witness_available():
        detail = "attested by brain-witness (privileged)"
    else:
        detail = "in-process (bootstrap trust: signed, but not unforgeable)"
    receipt = evidence.run_test(
        task_id=args.task,
        command=args.cmd_text,
        workspace=slug,
        session_id=session_id,
        timeout=args.timeout or 120,
    )
    status_str = "PASSED (exit 0)" if receipt["exit_code"] == 0 else f"FAILED (exit {receipt['exit_code']})"
    lines = [
        f"Test execution {status_str} for task {args.task}",
        f"  Receipt:  {receipt['receipt_id']}",
        f"  Command:  {receipt['command']}",
        f"  Witness:  {detail}",
        f"  Duration: {receipt['duration_ms']}ms",
    ]
    if receipt["output_snippet"]:
        lines.append(f"  Output:   {receipt['output_snippet']}")
    return out.payload(receipt, "\n".join(lines))


def cmd_receipts(args, out, cfg):
    slug = _slug(args)
    records = evidence.get_receipts(task_id=args.task or "", workspace=slug, limit=args.limit or 50)
    if out.as_json:
        return out.payload(records)
    if not records:
        return out.payload([], "No execution receipts found.")
    lines = [f"== EXECUTION RECEIPTS ({len(records)}) =="]
    unverified = [r for r in records if r.get("_attestation") != attest.VERIFIED]
    for r in records:
        ts = r.get("timestamp", "")[:19]
        rid = r.get("receipt_id", "")
        tid = r.get("task_id", "")
        code = r.get("exit_code", -1)
        dur = r.get("duration_ms", 0)
        cmd = r.get("command", "")
        mark = {"verified": "OK", "forged": "FORGED", "unsigned": "UNSIGNED",
                "no_trust_root": "NO-ROOT"}.get(r.get("_attestation"), "?")
        lines.append(f"  [{ts}] {rid} task={tid} exit={code} ({dur}ms) "
                     f"attest={mark} cmd={cmd[:36]}")
    if unverified:
        lines.append(f"  WARNING {len(unverified)} receipt(s) failed attestation and are "
                     f"not counted as evidence")
    return out.payload(records, "\n".join(lines))


def cmd_telemetry(args, out, cfg):
    slug = _slug(args)
    stats = telemetry.compute_telemetry(workspace=slug, all_workspaces=args.all_workspaces)
    agent = board.resolve_agent(args.agent) if args.agent else ""
    if agent:
        stats = {k: v for k, v in stats.items() if k == agent}
    if out.as_json:
        return out.payload(stats)
    if not stats:
        return out.payload({}, "No telemetry records observed yet.")
    lines = ["== EMPIRICAL AGENT TELEMETRY =="]
    for name, s in sorted(stats.items(), key=lambda item: item[1]["runs_total"], reverse=True):
        rate = f"{int(s['first_pass_rate'] * 100)}%"
        lines.append(
            f"  {name:<12} (role: {s['role']:<9})  pass-rate: {rate:<5}  runs: {s['runs_total']:<3}  "
            f"passed: {s['runs_passed']:<3}  failed: {s['runs_failed']:<3}  rework: {s['rework_count']:<2}  "
            f"avg: {s['avg_duration_ms']}ms"
        )
        if s["domains"]:
            dom_strs = [f"{d}: {int(dinfo['pass_rate'] * 100)}% ({dinfo['runs']})" for d, dinfo in s["domains"].items()]
            lines.append(f"    domains: {', '.join(dom_strs)}")
    return out.payload(stats, "\n".join(lines))


def cmd_post(args, out, cfg):
    if getattr(args, "to", None):
        res = messaging.send(
            body=args.text,
            sender=_agent(args.agent),
            recipient=args.to,
            workspace=_slug(args),
            task_id=getattr(args, "task_id", "") or "",
        )
        return out.payload(res, f"message {res['id']} sent to {res['to']} in '{res['workspace']}'")
    topic = getattr(args, "topic", "") or ""
    result = coordination.post(args.text, workspace=_slug(args), project=args.project or "",
                              tags=args.tags or "", agent=_agent(args.agent), topic=topic)
    top_str = f" [topic: {topic}]" if topic else ""
    return out.payload(result, f"context note {result['id']} posted{top_str} in '{result['workspace']}'")


def cmd_topology(args, out, cfg):
    slug = _slug(args)
    action = getattr(args, "action", "") or "show"
    if action == "validate":
        state, detail = topology.pin_status(slug)
        try:
            topo = topology.load(workspace=slug)
            if topo is None:
                return out.payload({"ok": True, "workspace": slug, "pin": state,
                                    "status": "no_topology_file"},
                                   f"no topology.yaml in workspace '{slug}' "
                                   f"(routing here is ungoverned)")
            return out.payload({"ok": True, "workspace": slug, "pin": state,
                                "seats": list(topo.get("seats", {}).keys())},
                               f"topology.yaml in '{slug}' is valid "
                               f"({len(topo.get('seats', {}))} seats); pin: {state} — {detail}")
        except TopologyError as exc:
            out.payload({"ok": False, "workspace": slug, "pin": state, "error": str(exc)},
                        f"topology validation failed: {exc}")
            return 2

    if action == "pin":
        if not os.path.isfile(const.WITNESS_BINARY):
            raise BrainError(f"no witness at {const.WITNESS_BINARY}: a topology pin is a "
                             "runtime signature, not a file an agent may write")
        call = ["sudo", const.WITNESS_BINARY, "pin-topology", "--workspace", slug,
                "--vault", str(VAULT)] + (["--note", args.note] if args.note else [])
        res = subprocess.run(call, capture_output=True, text=True)
        text = (res.stdout or res.stderr or "").strip()
        if res.returncode != 0:
            raise BrainError(f"witness refused: {text or f'exit {res.returncode}'}")
        return out.payload({"workspace": slug, "pinned": text}, text)

    if out.as_json:
        seats_list = topology.list_seats(workspace=slug)
        return out.payload({"workspace": slug, "seats": seats_list})

    rendered = topology.render_ascii(workspace=slug)
    return out.payload({"workspace": slug}, rendered)


def cmd_seat(args, out, cfg):
    slug = _slug(args)
    target_agent = getattr(args, "agent", "") or ""
    if target_agent:
        s_info = seats.get_seat(target_agent, workspace=slug)
        if out.as_json:
            return out.payload(s_info)
        lines = [
            f"Seat: {s_info['seat_id']}",
            f"  Role: {s_info['role']}",
            f"  Active Sessions: {len(s_info['active_sessions'])} {s_info['active_sessions']}",
            f"  Unread Messages: {s_info['unread_messages']}",
        ]
        if s_info["edges"]:
            lines.append("  Topology Edges:")
            for e in s_info["edges"]:
                lines.append(f"    - {e.get('kind')} -> {e.get('to')}")
        return out.payload(s_info, "\n".join(lines))

    all_seats = seats.list_seats(workspace=slug)
    if out.as_json:
        return out.payload(all_seats)
    lines = [f"== SEATS in '{slug}' ({len(all_seats)}) =="]
    for s in all_seats:
        lines.append(
            f"  [{s['seat_id']}] sessions: {s['active_session_count']}, unread: {s['unread_messages']}"
        )
    return out.payload(all_seats, "\n".join(lines))


def cmd_inbox(args, out, cfg):
    slug = _slug(args)
    target_agent = _agent(getattr(args, "agent", "") or "")

    ack_id = getattr(args, "ack", "") or ""
    if ack_id:
        res = messaging.acknowledge(ack_id, agent=target_agent, workspace=slug)
        return out.payload(res, f"message {ack_id} acknowledged")

    unread_only = not getattr(args, "all", False)
    messages = messaging.read_inbox(agent=target_agent, workspace=slug, unread_only=unread_only)
    if out.as_json:
        return out.payload(messages)

    status_str = "unread" if unread_only else "all"
    states = messaging.inbox_states(agent=target_agent, workspace=slug)
    lines = [f"== INBOX for '{target_agent}' in '{slug}' ({len(messages)} {status_str}) =="]
    if states.get("forged"):
        lines.append(f"  WARNING {states['forged']} message(s) failed attestation and are "
                     "labelled FORGED below")
    for m in messages:
        read_flag = " " if not m.get("read") else "✓"
        task_str = f" [task: {m['task_id']}]" if m.get("task_id") else ""
        seal = str(m.get("_attestation") or "unsigned")
        badge = "" if seal == attest.VERIFIED else f"  attest={seal.upper()}"
        lines.append(f"  [{read_flag}] {m['id']} from {m['from']}{task_str} "
                     f"({m.get('kind', 'message')}){badge}")
        lines.append(f"      {m['body'][:120]}")
    return out.payload(messages, "\n".join(lines))


def cmd_transcript(args, out, cfg):
    slug = _slug(args)
    target_id = args.id
    tail = getattr(args, "tail", 0) or 0
    grep = getattr(args, "grep", "") or ""

    tr = dispatch.get_transcript(target_id, workspace=slug, tail=tail, grep=grep)
    if out.as_json:
        return out.payload(tr)

    lines = [
        f"== Transcript: {target_id} ({tr['total_lines']} lines) ==",
        tr["content"],
    ]
    return out.payload(tr, "\n".join(lines))


def cmd_read(args, out, cfg):
    slug = _slug(args)
    topic = getattr(args, "topic", "") or ""
    notes = coordination.read_notes(query=args.query or "", workspace=slug,
                                    project=args.project or "", agent=args.agent or "",
                                    tag=args.tag or "", topic=topic, limit=args.limit or 0,
                                    all_workspaces=args.all_workspaces)
    if out.as_json:
        return out.payload(notes)
    topic_header = f" topic '{topic}'" if topic else ""
    lines = [f"== CONTEXT in '{slug}'{topic_header} ({len(notes)}) =="]
    for note in notes:
        first = (note["body"] or "").splitlines()
        top_str = f" [{note['topic']}]" if note.get("topic") else ""
        lines.append(f"  [{note['agent']}]{top_str} ({note['workspace']}) "
                     f"{first[0][:110] if first else ''} [{time_ago(note.get('created'))}]")
        lines.append(f"      id: {note['id']}")
    return out.payload({"notes": len(notes)}, "\n".join(lines))


def cmd_wait(args, out, cfg):
    slug = _slug(args)
    timeout = getattr(args, "timeout", 60) or 60
    topic = getattr(args, "topic", "") or ""
    agent = getattr(args, "agent", "") or ""
    after = getattr(args, "after", "") or ""

    notes = coordination.wait_for_notes(
        workspace=slug,
        topic=topic,
        agent=agent,
        after=after,
        timeout=timeout,
        all_workspaces=args.all_workspaces,
    )
    if not notes:
        if out.as_json:
            return out.payload([], f"Timed out after {timeout}s with no new notes matching filter")
        print(f"Timed out after {timeout}s with no new notes matching filter.", file=sys.stderr)
        return 1

    if out.as_json:
        return out.payload(notes)

    lines = [f"== NEW NOTES in '{slug}' ({len(notes)}) =="]
    for note in notes:
        top_str = f" [{note['topic']}]" if note.get("topic") else ""
        lines.append(f"  [{note['agent']}]{top_str} {note['body']} [{time_ago(note.get('created'))}]")
        lines.append(f"      id: {note['id']}")
    return out.payload({"notes": len(notes)}, "\n".join(lines))


def cmd_watch(args, out, cfg):
    slug = _slug(args)
    topic = getattr(args, "topic", "") or ""
    agent = getattr(args, "agent", "") or ""
    topic_str = f" (topic: {topic})" if topic else ""
    print(f"Streaming live context notes for '{slug}'{topic_str}... (Ctrl-C to stop)", file=sys.stderr)
    try:
        coordination.watch_notes(
            workspace=slug,
            topic=topic,
            agent=agent,
            all_workspaces=args.all_workspaces,
        )
    except KeyboardInterrupt:
        return 0
    return 0


def _stdin_files() -> list:
    """Pull candidate file paths out of a hook's JSON payload on stdin.

    Claude Code's PreToolUse hook pipes `{tool_name, tool_input:{file_path: ...}}`; other
    clients pass similar shapes. Reading defensively means a client that changes its
    payload degrades to "no files given" instead of crashing every tool call.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return []
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return []
    if not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except ValueError:
        return []
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("file_path", "filePath", "path", "paths", "file_paths") \
                        and isinstance(value, (str, list)):
                    found.extend(value if isinstance(value, list) else [value])
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return [str(f) for f in found if isinstance(f, str) and f.strip()]


def cmd_guard(args, out, cfg):
    """Enforcement hook for any agent that can run a command before a tool call."""
    slug = _slug(args)
    agent = _agent(args.agent)
    files = list(_files(getattr(args, "files", "") or ""))
    if getattr(args, "stdin_json", False):
        files += _stdin_files()
    decision = coordination.admit(agent, files=files, workspace=slug)
    if decision["ok"]:
        return 0
    # Asked once, and only here: a grant is spent by the asking, whether or not it wins.
    granted, why = grants.bypass(seat=agent, action="guard", workspace=slug)
    if granted:
        print(f"[brain-guard] override for {agent}: {why} — was blocked: {decision['reason']}")
        return 0
    print(
        f"[brain-guard] BLOCKED ({agent} in '{slug}'): {decision['reason']}\n"
        f"Clearance:  brain start --agent {agent} --task 'what you are about to do' "
        f"--files {','.join(files) or 'a.py,b.py'}\n"
        f"Then retry. Break glass needs a human: "
        f"brain bypass-grant --seat {agent} --reason 'why', then "
        f"export {grants.TOKEN_ENV}=<token> (one use).",
        file=sys.stderr)
    return 1


# ---- agents / setup ------------------------------------------------------


def cmd_setup(args, out, cfg):
    actions = agents.configure(targets=args.agent or None, dry_run=args.dry_run)
    if not args.no_shim:
        actions += agents.install_shim(dry_run=args.dry_run)
    actions += agents.write_user_vault_pointer(dry_run=args.dry_run)
    if args.bind:
        actions += ws_mod.bind_directory(_slug(args), args.bind, set_git_config=True,
                                         pointer=True, skill=True)
    if not args.no_projects:
        agents.configure_projects(actions, dry_run=args.dry_run)
    return out.payload({"actions": actions},
                       "== SETUP ==\n" + "\n".join(f"  {a}" for a in actions)
                       + "\n\nany agent can now use:  brain bootstrap")


def cmd_bootstrap(args, out, cfg):
    out.raw(agents.bootstrap_brief(agent=args.agent or "", workspace=_slug(args)))
    return 0


def cmd_whoami(args, out, cfg):
    slug = _slug(args)
    agent = _agent(args.agent)
    role = board.role_of(agent)
    active = [s for s in coordination.list_sessions(workspace=slug, active_only=True)
              if board.resolve_agent(s["fm"].get("agent")) == agent]
    info = {
        "agent": agent, "role": role, "workspace": slug,
        "workspace_path": ws_mod.entry(slug).get("path", ""),
        "vault": str(VAULT),
        "session": active[0]["id"] if active else None,
        "leases": _files(active[0]["fm"].get("files")) if active else [],
        "hint": ROLE_HINT.get(role, ""),
        "detected_from": os.getcwd(),
        "identity": "declared by the runtime (BRAIN_AGENT)" if os.environ.get("BRAIN_AGENT")
                    else "asserted by this call — a flag, not a credential",
    }
    lines = [
        f"agent:     {agent} ({role})",
        f"identity:  {info['identity']}",
        f"workspace: {slug}  ->  {info['workspace_path'] or '(unbound)'}",
        f"vault:     {VAULT}",
        f"session:   {info['session'] or 'none — run `brain start`'}",
        f"leases:    {', '.join(info['leases']) if info['leases'] else 'none'}",
        f"role hint: {info['hint']}",
    ]
    return out.payload(info, "\n".join(lines))


def cmd_doctor(args, out, cfg):
    checks = []

    def check(name, ok, detail="", advisory=False):
        """`advisory` marks a condition that is informational, not broken — the daemon
        being stopped is a valid state if you drive the board by hand."""
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       "advisory": advisory})

    check("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    check("sqlite fts5", index.available(), "BM25 search enabled" if index.available()
          else "falling back to LIKE scans")
    check("vault initialised", (VAULT / const.META_DIR).is_dir(), str(VAULT))
    check("vault is a git repo", vcs.is_repo(), vcs.current_branch() or "no branch")
    check("workspaces registered", bool(ws_mod.all_slugs()),
          ", ".join(ws_mod.all_slugs()))
    missing = [slug for slug in ws_mod.all_slugs()
               if not ws_mod.workspace_dir(slug).is_dir()]
    check("workspace dirs exist", not missing, ", ".join(missing) or "all present")
    problems = store.scan_problems()
    check("record integrity", not problems, f"{len(problems)} problem(s)")
    for path in api_checks():
        check(path[0], path[1], path[2])
    detected = {name: path for name, path in agents.detect_agents().items() if path}
    check("agent CLIs detected", bool(detected),
          ", ".join(f"{k}" for k in detected) or "none")
    check("shim on PATH", agents.shim_on_path(), str(agents.shim_path()))
    check("agent skill installed", agents.skill_installed(),
          ", ".join(str(p) for p in agents.skill_targets() if p.exists())
          or "run `brain setup` so agents discover the brain on their own")
    dstatus = daemon.daemon_status()
    check("daemon", dstatus["active"],
          dstatus.get("detail", "") + " (start it with `brain daemon` if you want the "
          "board driven automatically)", advisory=True)
    runs = [r for r in dispatch.all_run_records() if r.get("returncode") is None]
    check("in-flight dispatches", True, f"{len(runs)} process(es) still running")
    tstatus = attest.status()
    check("attestation trust root", tstatus["mode"] == "installed",
          f"{tstatus['mode']}: {tstatus['boundary']}", advisory=tstatus["mode"] != "installed")
    unpinned = [f"{slug}({topology.pin_status(slug)[0]})" for slug in ws_mod.all_slugs()
                if topology.pin_status(slug)[0] != "pinned"]
    check("topology pinned", not unpinned,
          ", ".join(unpinned) or "every workspace matches a signed pin", advisory=True)
    pending = grants.list_grants()
    check("unspent bypass grants", not pending,
          ", ".join(f"{g['grant_id']}→{g['seat']}" for g in pending) or "none", advisory=True)

    lines = ["== DOCTOR =="]
    for item in checks:
        marker = "OK  " if item["ok"] else ("WARN" if item.get("advisory") else "FAIL")
        lines.append(f"  {marker} {item['check']}"
                     + (f" — {item['detail']}" if item["detail"] else ""))
    bad = [c for c in checks if not c["ok"] and not c.get("advisory")]
    lines.append(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed")
    out.payload({"checks": checks, "ok": not bad}, "\n".join(lines))
    return 0 if not bad else 1


def api_checks():
    """Agent config files we expect to own, and whether they point at this vault."""
    results = []
    for label, path, needle in (
        ("claude MCP config", Path.home() / ".claude.json", str(VAULT)),
        ("codex MCP config", Path.home() / ".codex" / "config.toml", "[mcp_servers.second-brain]"),
        ("opencode MCP config", Path.home() / ".config" / "opencode" / "opencode.json",
         "second-brain"),
        ("gemini MCP config", Path.home() / ".gemini" / "config" / "mcp_config.json",
         "second-brain"),
    ):
        if not path.exists():
            results.append((label, False, "not configured (run `brain setup`)"))
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            results.append((label, False, str(exc)))
            continue
        results.append((label, needle in text,
                        "ok" if needle in text else "stale or missing entry"))
    return results


# ---- dispatch / daemon / server -----------------------------------------


def cmd_dispatch(args, out, cfg):
    result = dispatch.dispatch(args.id, agent=args.agent or "", workspace=_slug(args),
                              tab=args.tab, wait=args.wait, timeout=args.timeout)
    if not result.get("ok"):
        out.payload(result, f"dispatch failed: {result.get('detail')}")
        return 1
    message = (f"dispatched {result['task_id']} to {result['agent']} "
               f"({result['mode']}, session {result['session_id']})")
    if result.get("pid"):
        message += f"\n  pid {result['pid']} — log: {result['log']}"
    return out.payload(result, message)


def cmd_auto_cycle(args, out, cfg):
    result = daemon.auto_cycle(workspace=_slug(args), project=args.project or "",
                               tab=args.tab)
    if result.get("action") == "idle":
        return out.payload(result, "board is clear — nothing to dispatch")
    if result.get("action") == "skip" or not result.get("ok"):
        return out.payload(result, f"skipped {result.get('task_id')}: {result.get('detail')}")
    return out.payload(result, f"dispatched {result['task_id']} to {result['agent']} "
                               f"({result.get('detail')})")


def cmd_runs(args, out, cfg):
    runs = dispatch.all_run_records(_slug(args))[: args.limit]
    lines = ["== DISPATCH RUNS =="]
    for run in runs:
        state = "running" if run.get("returncode") is None else f"exit {run.get('returncode')}"
        lines.append(f"  {run.get('started')} {run.get('agent')} {run.get('task_id')} "
                     f"[{run.get('workspace')}] {state}")
        if run.get("log"):
            lines.append(f"      log: {run['log']}")
    return out.payload(runs, "\n".join(lines) if runs else "no dispatches recorded")


def cmd_daemon(args, out, cfg):
    return daemon.run(interval=args.interval, workspace=_slug(args), project=args.project or "",
                      max_attempts=args.max_retries, once=args.once, commit=not args.no_commit,
                      cfg=cfg)


def cmd_serve(args, out, cfg):
    from . import http
    return http.main(port=args.port, host=args.host)


def cmd_reindex(args, out, cfg):
    count = index.reindex_all(verbose=args.verbose)
    l0.write_all()
    return out.payload({"indexed": count}, f"reindexed {count} document(s)")


# ---- argument parsing ----------------------------------------------------


def _files(value) -> list:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brain",
        description="Second Brain — shared memory, board and coordination for coding agents",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("-w", "--workspace", default="", help="workspace slug (default: detect from cwd)")
    parser.add_argument("--all-workspaces", action="store_true", help="read every workspace, not just this one")
    sub = parser.add_subparsers(dest="cmd")

    def add(name, help_text="", aliases=()):
        child = sub.add_parser(name, help=help_text, aliases=list(aliases))
        child.add_argument("-w", "--workspace", default=argparse.SUPPRESS,
                           help="workspace slug (default: detect from cwd)")
        child.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
        child.add_argument("--all-workspaces", action="store_true",
                           help="read every workspace, not just this one")
        return child

    add("init", "create/patch the vault skeleton")
    add("migrate", "move pre-workspace records into workspace directories").add_argument(
        "--dry-run", action="store_true")
    add("status", "vault, board, lease and daemon health")
    add("doctor", "diagnose this installation end to end")
    add("reindex", "force a full search index rebuild").add_argument("--verbose",
                                                                    action="store_true")
    add("brief", "print the L0 brief for this workspace (this is your context)").add_argument(
        "--write", action="store_true", help="also regenerate the cached files")
    add("whoami", "what the brain thinks you are and where you are").add_argument(
        "--agent", default="")

    claim = add("claim", "record a durable fact")
    claim.add_argument("text")
    claim.add_argument("--status", default="active", choices=const.STATUSES)
    claim.add_argument("--confidence", type=float, default=0.9)
    claim.add_argument("--source", default="")
    claim.add_argument("--tags", default="")
    claim.add_argument("--commit", default="", help="git commit SHA this claim is verified against")
    claim.add_argument("--depends-on", default="", help="comma-separated file paths this claim depends on")
    claim.add_argument("--global", dest="global_scope", action="store_true",
                       help="share this claim with every workspace")
    claim.add_argument("--maturity", default="", choices=list(const.CLAIM_MATURITIES) + [""],
                       help="epistemic maturity level (provisional, established, canonical)")

    reval = add("revalidate", "re-verify a claim against current Git HEAD (restores active status)")
    reval.add_argument("id")
    reval.add_argument("--commit", default="")
    reval.add_argument("--note", default="")

    elevate_p = add("elevate", "elevate a claim along the epistemic maturity ladder")
    elevate_p.add_argument("id")
    elevate_p.add_argument("--maturity", default="canonical", choices=list(const.CLAIM_MATURITIES))
    elevate_p.add_argument("--note", default="")

    review = add("review", "mark a claim as reviewed now (resets its staleness clock)")
    review.add_argument("id")
    review.add_argument("--note", default="")

    supersede = add("supersede", "replace a claim with a newer one")
    supersede.add_argument("id")
    supersede.add_argument("newid")
    dispute = add("dispute", "keep the evidence but stop trusting a claim")
    dispute.add_argument("id")
    dispute.add_argument("--reason", default="")
    dispute.add_argument("--by", default="")
    promote = add("promote", "turn a context note into a durable claim")
    promote.add_argument("id")
    promote.add_argument("--confidence", type=float, default=0.9)
    promote.add_argument("--tags", default="")

    recall = add("recall", "search the knowledge base (BM25)")
    recall.add_argument("query", nargs="?")
    recall.add_argument("--tag")
    recall.add_argument("--status")
    recall.add_argument("--maturity", default="", choices=list(const.CLAIM_MATURITIES) + [""],
                        help="filter by epistemic maturity level")
    recall.add_argument("--limit", type=int, default=0)
    recall.add_argument("--all", action="store_true",
                        help="include withheld (superseded/disputed/expired) claims")
    related = add("related", "claims linked to this one")
    related.add_argument("id")
    verify = add("verify", "schema, chain and round-trip check")
    verify.add_argument("id", nargs="?")
    verify.add_argument("--fix", action="store_true",
                        help="clear dangling chain links (recorded in the body)")

    sweep = add("sweep", "expire sessions, flag stale claims, rebuild L0")
    sweep.add_argument("--commit", action="store_true")

    ws = add("workspaces", "list/add/bind/alias/remove workspaces", aliases=("ws",))
    ws.add_argument("action", nargs="?", default="list",
                    choices=("list", "add", "bind", "remove", "default", "alias", "merge"))
    ws.add_argument("name", nargs="?")
    ws.add_argument("path", nargs="?")
    ws.add_argument("--description", default="")
    ws.add_argument("--default", action="store_true")
    ws.add_argument("--no-git", action="store_true")
    ws.add_argument("--display-name", default="")
    ws.add_argument("--alias", action="append", default=[])
    ws.add_argument("--pointer", action="store_true",
                    help="append a brain pointer to the project's AGENTS.md/CLAUDE.md")
    ws.add_argument("--skill", action="store_true",
                    help="install .agents/skills/second-brain so any agent there finds the "
                         "brain with no configuration")
    ws.add_argument("--keywords", default=[], action="append",
                    help="topical terms used by `brain reclassify` to scope records")
    ws.add_argument("--replace", action="store_true",
                    help="replace aliases/keywords instead of merging (use to narrow)")

    rep = add("repair", "recover records with a broken frontmatter block")
    rep.add_argument("--dry-run", action="store_true")

    recl = add("reclassify", "move misfiled records into the right workspace")
    recl.add_argument("--dry-run", action="store_true")

    goal_prop = add("goal-propose", "propose a high-level goal and compile its task DAG")
    goal_prop.add_argument("--goal", default="", help="goal description")
    goal_prop.add_argument("--tasks-json", default="", help="JSON string with task definitions")
    goal_prop.add_argument("-f", "--file", default="", help="path to JSON file with proposal")
    goal_prop.add_argument("--spec-title", default="", help="optional title for created spec")
    goal_prop.add_argument("--spec-desc", default="", help="optional description for created spec")
    goal_prop.add_argument("--actor", default="agent:jarvis", help="actor proposing the goal")
    goal_prop.add_argument("--project", default="", help="project name")

    spec_create = add("spec-create", "write an upstream spec")
    spec_create.add_argument("--title", required=True)
    spec_create.add_argument("--spec", required=True)
    spec_create.add_argument("--project", default="")
    spec_create.add_argument("--phases", default="")
    specs = add("specs", "list specs")
    specs.add_argument("--project", default="")

    task_create = add("task-create", "add a card")
    task_create.add_argument("--title", required=True)
    task_create.add_argument("--project", default="")
    task_create.add_argument("--spec", default="")
    task_create.add_argument("--agent", default="")
    task_create.add_argument("--phase", default="")
    task_create.add_argument("--files", default="")
    task_create.add_argument("--depends-on", default="", help="comma-separated prerequisite task IDs")
    task_create.add_argument("--status", default="", choices=list(const.TASK_STATUSES) + [""])
    task_create.add_argument("--coordination-required", action="store_true", help="require Deliberation Record before execution (INV-008)")
    move = add("move", "advance a card (the move to done needs review evidence)")
    move.add_argument("id")
    move.add_argument("--status", required=True, choices=const.TASK_STATUSES)
    move.add_argument("--agent", default="")
    move.add_argument("--notes", default="")
    move.add_argument("--tests", default="")
    move.add_argument("--closure", default="", choices=list(const.CLOSURE_REASONS) + [""],
                      help="hot-potato closure reason (required for done)")
    move.add_argument("--closure-target", default="",
                      help="target agent or blocker ID for closure")
    move.add_argument("--force", action="store_true")
    tasks = add("tasks", "show the board")
    tasks.add_argument("--project", default="")
    tasks.add_argument("--status", default="")
    tasks.add_argument("--agent", default="")
    route = add("route", "decide direct execution vs the full pipeline")
    route.add_argument("--agent", required=True)
    route.add_argument("--prompt", required=True)
    route.add_argument("--project", default="")
    nxt = add("next", "the next actionable step for this agent")
    nxt.add_argument("--agent", required=True)
    nxt.add_argument("--project", default="")

    start = add("start", "open a session (and lease the files you will touch)")
    start.add_argument("--agent", required=True)
    start.add_argument("--project", default="")
    start.add_argument("--task", default="")
    start.add_argument("--task-id", default="")
    start.add_argument("--files", default="")
    start.add_argument("--branch", default="")
    start.add_argument("--worktree", default="")
    start.add_argument("--lease", type=int, default=0)
    start.add_argument("--force", action="store_true")
    update = add("update", "append progress or extend a lease")
    update.add_argument("id")
    update.add_argument("--progress", default="")
    update.add_argument("--files", default="")
    update.add_argument("--extend-lease", type=int, default=0)
    reserve = add("reserve", "lease more files")
    reserve.add_argument("id")
    reserve.add_argument("--files", required=True)
    reserve.add_argument("--lease", type=int, default=0)
    reserve.add_argument("--force", action="store_true")
    check = add("check-files", "ask before editing files another agent holds")
    check.add_argument("--files", required=True)
    end = add("end", "close a session, release leases, hand off")
    end.add_argument("id")
    end.add_argument("--summary", default="")
    end.add_argument("--target-agent", default="")
    end.add_argument("--next-steps", default="")
    end.add_argument("--modified-files", default="")
    end.add_argument("--test-status", default="")
    end.add_argument("--closure", default="", choices=list(const.CLOSURE_REASONS) + [""],
                     help="closure reason for task if ending session")
    end.add_argument("--closure-target", default="",
                     help="target agent or blocker ID for closure")
    sessions = add("sessions", "who is working on what right now")
    sessions.add_argument("--agent", default="")
    sessions.add_argument("--project", default="")
    sessions.add_argument("--active", action="store_true")
    post = add("post", "post a note the other agents can see immediately")
    post.add_argument("text")
    post.add_argument("--project", default="")
    post.add_argument("--tags", default="")
    post.add_argument("--topic", default="", help="topic or thread for this note")
    post.add_argument("--agent", default="")
    post.add_argument("--to", default="", help="directed message recipient agent (inbox)")
    post.add_argument("--task-id", default="", help="task ID linked to message")
    read = add("read", "read recent notes")
    read.add_argument("--query", default="")
    read.add_argument("--project", default="")
    read.add_argument("--agent", default="")
    read.add_argument("--tag", default="")
    read.add_argument("--topic", default="", help="filter notes by topic")
    read.add_argument("--limit", type=int, default=0)

    wait_cmd = add("wait", "block execution until new context notes arrive")
    wait_cmd.add_argument("--topic", default="", help="filter notes by topic")
    wait_cmd.add_argument("--agent", default="", help="filter notes by sender agent")
    wait_cmd.add_argument("--after", default="", help="only notes created after this note ID or timestamp")
    wait_cmd.add_argument("--timeout", type=int, default=60, help="timeout in seconds (default: 60)")

    watch_cmd = add("watch", "stream live context notes in real time")
    watch_cmd.add_argument("--topic", default="", help="filter notes by topic")
    watch_cmd.add_argument("--agent", default="", help="filter notes by sender agent")

    delib = add("deliberate", "multi-agent deliberation room protocol", aliases=("room",))
    delib.add_argument("action", nargs="?", default="status",
                       choices=["open", "post", "propose", "object", "resolve", "presence", "adjudicate", "status", "verify"],
                       help="deliberation action")
    delib.add_argument("--task", default="", help="task ID")
    delib.add_argument("--risk", default="normal", choices=["normal", "high", "critical"])
    delib.add_argument("--mode", default="normal", choices=["normal", "council"])
    delib.add_argument("--participants", default="", help="comma-separated required participants")
    delib.add_argument("--domains", default="", help="comma-separated domains")
    delib.add_argument("--max-rounds", type=int, default=3)
    delib.add_argument("--agent", default="", help="agent actor")
    delib.add_argument("--sender", default="", help="sender agent")
    delib.add_argument("--actor", default="", help="acting agent")
    delib.add_argument("--body", default="", help="message or objection body")
    delib.add_argument("--type", default="SUGGESTION", help="message type (QUESTION, SUGGESTION, OBJECTION, EVIDENCE, ADJUDICATION)")
    delib.add_argument("--recipient", default="", help="target recipient")
    delib.add_argument("--severity", default="medium", choices=list(const.DELIBERATION_SEVERITIES))
    delib.add_argument("--ref", default="", help="comma-separated references or evidence IDs")
    delib.add_argument("--plan", default="", help="semicolon-separated proposal plan steps")
    delib.add_argument("--files", default="", help="comma-separated expected files")
    delib.add_argument("--risks", default="", help="semicolon-separated risks")
    delib.add_argument("--prop-id", default="", help="proposal ID")
    delib.add_argument("--notes", default="", help="resolution notes or message notes")
    delib.add_argument("--state", default="ANALYZING", choices=list(const.DELIBERATION_PRESENCE_STATES), help="presence state")
    delib.add_argument("--focus", default="", help="presence focus or current work description")

    who_working = add("who-working", "show active presence for a task or across the workspace")
    who_working.add_argument("--task", default="")
    guard = add("guard", "enforcement hook: refuse writes without a session")
    guard.add_argument("--agent", default="")
    guard.add_argument("--files", default="",
                        help="files the tool is about to touch, so a lease conflict can "
                             "be refused precisely instead of blocking everything")
    guard.add_argument("--stdin-json", action="store_true",
                        help="read the hook's JSON payload from stdin (Claude Code style)")

    setup = add("setup", "wire every agent CLI and project on this machine")
    setup.add_argument("--agent", action="append", default=[])
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument("--no-shim", action="store_true")
    setup.add_argument("--no-projects", action="store_true",
                       help="do not touch registered project directories")
    setup.add_argument("--bind", default="", help="also bind this directory to the workspace")
    boot = add("bootstrap", "print the brief that onboards a new agent")
    boot.add_argument("--agent", default="")

    dispatch_p = add("dispatch", "run the assigned agent on a card")
    dispatch_p.add_argument("id")
    dispatch_p.add_argument("--agent", default="")
    dispatch_p.add_argument("--tab", action="store_true", help="open it in a terminal window")
    dispatch_p.add_argument("--wait", action="store_true", help="block until it exits")
    dispatch_p.add_argument("--timeout", type=int, default=0)
    add("auto-cycle", "dispatch the next actionable card exactly once")
    runs = add("runs", "dispatch history with exit codes")
    runs.add_argument("--limit", type=int, default=10)
    daemon_p = add("daemon", "poll the board and drive it continuously")
    daemon_p.add_argument("--interval", type=int, default=15)
    daemon_p.add_argument("--project", default="")
    daemon_p.add_argument("--max-retries", type=int, default=daemon.MAX_ATTEMPTS)
    daemon_p.add_argument("--once", action="store_true")
    daemon_p.add_argument("--no-commit", action="store_true")
    serve = add("serve", "run the Mission Control HTTP API + dashboard")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    serve.add_argument("--host", default=os.environ.get("BRAIN_HOST", "127.0.0.1"))
    events_p = add("events", "query the append-only event stream")
    events_p.add_argument("--date", default="", help="filter by date (YYYY-MM-DD)")
    events_p.add_argument("--type", default="", help="filter by event type")
    events_p.add_argument("--task", default="", help="filter by task id")
    events_p.add_argument("--stage", default="", help="filter by stage (PROPOSE, AUTHORIZE, OBSERVE, RECORD)")
    events_p.add_argument("--actor", default="", help="filter by actor")
    events_p.add_argument("--limit", type=int, default=50, help="max events to return")
    events_p.add_argument("--oldest", action="store_true", help="show oldest first")

    rec_ev = add("record-evidence", "REFUSED: an asserted exit code is not evidence "
                                    "(kept as a tripwire; use `brain test`)")
    rec_ev.add_argument("--task", required=True, help="task ID")
    rec_ev.add_argument("--cmd-text", required=True, help="command that ran")
    rec_ev.add_argument("--exit-code", type=int, required=True, help="command returncode")
    rec_ev.add_argument("--stdout", default="", help="stdout captured")
    rec_ev.add_argument("--stderr", default="", help="stderr captured")
    rec_ev.add_argument("--duration", type=int, default=0, help="duration in milliseconds")
    rec_ev.add_argument("--session", default="", help="session ID")

    add("attest", "show the attestation trust root, key fingerprint and witness state")
    bg = add("bypass-grant", "ask the witness for a single-use bypass grant (needs a password)")
    bg.add_argument("--seat", default="", help="the one seat this grant covers")
    bg.add_argument("--reason", required=True, help="the emergency, >= 10 chars")
    bg.add_argument("--minutes", type=int, default=30, help="validity window (max 240)")
    add("grants", "list unspent bypass grants and how far they can be trusted")
    add("verify-boundary", "run the adversarial probes and report n blocked / n open")

    test_cmd = add("test", "execute tests for a task and record machine receipt")
    test_cmd.add_argument("--task", required=True, help="task ID")
    test_cmd.add_argument("--cmd-text", required=True, help="test command to execute")
    test_cmd.add_argument("--session", default="", help="session ID")
    test_cmd.add_argument("--timeout", type=int, default=120, help="timeout in seconds")

    rcpts = add("receipts", "list machine execution receipts")
    rcpts.add_argument("--task", default="", help="filter by task ID")
    rcpts.add_argument("--limit", type=int, default=50, help="max receipts to return")

    telem_p = add("telemetry", "view empirical worker capability telemetry")
    telem_p.add_argument("--agent", default="", help="filter by agent")

    add("verify-invariants", "execute the constitutional invariants test suite")

    topo_cmd = add("topology", "show or validate agent topology graph")
    topo_cmd.add_argument("action", nargs="?", default="show",
                          choices=["show", "validate", "pin"],
                          help="show, validate against the signed pin, or pin (needs a password)")
    topo_cmd.add_argument("--note", default="", help="why this policy version was approved")

    seat_cmd = add("seat", "show declared agent seats and active session bindings")
    seat_cmd.add_argument("agent", nargs="?", default="", help="specific agent seat to inspect")

    sq_cmd = add("squad", "manage declarative agent squads (lead, builder, reviewer, qa)")
    sq_cmd.add_argument("action", nargs="?", default="show", choices=["show", "init", "set"],
                        help="squad action (default: show)")
    sq_cmd.add_argument("role", nargs="?", default="", help="role to assign (lead, builder, reviewer, qa)")
    sq_cmd.add_argument("agent", nargs="?", default="", help="agent seat to assign to the role")
    sq_cmd.add_argument("--name", default="", help="squad name")

    inbox_cmd = add("inbox", "read directed messages sent to an agent")
    inbox_cmd.add_argument("--agent", default="", help="agent inbox to read (default: BRAIN_AGENT)")
    inbox_cmd.add_argument("--ack", default="", help="acknowledge message ID as read")
    inbox_cmd.add_argument("--all", action="store_true", help="show all messages including read")

    tr_cmd = add("transcript", "view or search agent run transcripts")
    tr_cmd.add_argument("id", help="session ID or task ID")
    tr_cmd.add_argument("--tail", type=int, default=0, help="show last N lines")
    tr_cmd.add_argument("--grep", default="", help="search regex pattern")

    tui_cmd = add("tui", "live terminal dashboard for sessions, board, and chat")
    tui_cmd.add_argument("--once", action="store_true", help="render a single static snapshot")
    tui_cmd.add_argument("--interval", type=float, default=2.0, help="refresh interval in seconds")

    return parser


HANDLERS = {
    "init": cmd_init, "migrate": cmd_migrate, "status": cmd_status, "doctor": cmd_doctor,
    "reindex": cmd_reindex, "brief": cmd_brief, "whoami": cmd_whoami,
    "claim": cmd_claim, "review": cmd_review, "revalidate": cmd_revalidate, "elevate": cmd_elevate,
    "supersede": cmd_supersede,
    "dispute": cmd_dispute, "promote": cmd_promote, "recall": cmd_recall,
    "related": cmd_related, "verify": cmd_verify, "sweep": cmd_sweep,
    "verify-invariants": cmd_verify_invariants,
    "workspaces": cmd_workspaces, "ws": cmd_ws, "repair": cmd_repair,
    "reclassify": cmd_reclassify,
    "goal-propose": cmd_goal_propose,
    "spec-create": cmd_spec_create, "specs": cmd_specs,
    "task-create": cmd_task_create, "move": cmd_move, "tasks": cmd_tasks,
    "route": cmd_route, "next": cmd_next,
    "start": cmd_start, "update": cmd_update, "reserve": cmd_reserve,
    "check-files": cmd_check_files, "end": cmd_end, "sessions": cmd_sessions,
    "events": cmd_events,
    "record-evidence": cmd_record_evidence, "attest": cmd_attest, "test": cmd_test, "receipts": cmd_receipts,
    "bypass-grant": cmd_bypass_grant, "grants": cmd_grants,
    "verify-boundary": cmd_verify_boundary,
    "telemetry": cmd_telemetry,
    "post": cmd_post, "read": cmd_read, "guard": cmd_guard,
    "wait": cmd_wait, "watch": cmd_watch,
    "deliberate": cmd_deliberate, "room": cmd_room,
    "who-working": cmd_who_working,
    "setup": cmd_setup, "bootstrap": cmd_bootstrap,
    "dispatch": cmd_dispatch, "auto-cycle": cmd_auto_cycle, "runs": cmd_runs,
    "daemon": cmd_daemon, "serve": cmd_serve,
    "topology": cmd_topology, "seat": cmd_seat, "squad": cmd_squad, "inbox": cmd_inbox,
    "transcript": cmd_transcript, "tui": cmd_tui,
}


def main(argv=None) -> int:
    stdout_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 1
    handler = HANDLERS.get(args.cmd)
    if handler is None:
        parser.print_help()
        return 1
    out = Out(as_json=bool(getattr(args, "json", False)))

    try:
        cfg = store.config()
        if args.cmd in ("daemon", "serve"):
            # Long-running processes manage their own locking.
            return handler(args, out, cfg)
        if args.cmd in ("guard", "brief", "whoami", "bootstrap", "status", "doctor", "serve", "events", "receipts", "telemetry", "topology", "seat", "squad", "tui", "attest", "transcript", "grants", "bypass-grant", "verify-boundary", "wait", "watch"):
            # Read-only or self-contained: no lock, so the dashboard never blocks.
            return handler(args, out, cfg)
        with lock():
            return handler(args, out, cfg)
    except TimeoutError as exc:
        print(f"busy: {exc}", file=sys.stderr)
        return 1
    except UnverifiedEvidenceError as exc:
        print(f"REFUSED (unverified evidence): {exc}", file=sys.stderr)
        return 2
    except ReviewGate as exc:
        print(f"REFUSED (review gate): {exc}", file=sys.stderr)
        return 2
    except DependencyBlockedError as exc:
        print(f"REFUSED (dependency blocked): {exc}", file=sys.stderr)
        return 2
    except CycleDetectedError as exc:
        print(f"REFUSED (cycle detected): {exc}", file=sys.stderr)
        return 2
    except TopologyError as exc:
        print(f"REFUSED (topology routing): {exc}", file=sys.stderr)
        return 2
    except LeaseConflict as exc:
        print(f"REFUSED (lease conflict): {exc}", file=sys.stderr)
        return 2
    except NotFound as exc:
        print(f"not found: {exc}", file=sys.stderr)
        return 1
    except BrainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
