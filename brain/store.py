# -*- coding: utf-8 -*-
"""Workspace-scoped record storage.

One record is one markdown file under `workspaces/<slug>/<kind>/`. This module owns
ids, paths, parse/validate, atomic writes and lease computation; the domain rules
live in knowledge.py, board.py and coordination.py.

Reads are deliberately tolerant: a single malformed file must not take down
`brain status`. `scan_problems()` exists so `brain verify` can still report it.
"""

import re
import uuid
from datetime import datetime
from pathlib import Path

from . import const, frontmatter, index, workspaces as ws_mod
from .errors import BrainError, NotFound
from .paths import (VAULT, atomic_write, parse_ts, read_text, now)

KINDS = ("claims", "specs", "tasks", "sessions", "context")

DIRS = {
    "claims": "claims",
    "specs": "specs",
    "tasks": "tasks",
    "sessions": "sessions",
    "context": "context",
}
PREFIXES = {"claims": "", "specs": "spec-", "tasks": "t-", "sessions": "s-", "context": "ctx-"}
GLOBS = {"claims": "*.md", "specs": "spec-*.md", "tasks": "t-*.md",
         "sessions": "s-*.md", "context": "ctx-*.md"}
SCHEMAS = {
    "claims": (const.CLAIM_REQUIRED, const.STATUSES, const.CLAIM_FM_ORDER),
    "specs": (const.SPEC_REQUIRED, None, const.SPEC_FM_ORDER),
    "tasks": (const.TASK_REQUIRED, const.TASK_STATUSES, const.TASK_FM_ORDER),
    "sessions": (const.SESSION_REQUIRED, None, const.SESSION_FM_ORDER),
    "context": (const.CONTEXT_REQUIRED, None, const.CONTEXT_FM_ORDER),
}


def new_id(kind: str) -> str:
    day = datetime.now().strftime("%Y%m%d")
    return f"{PREFIXES[kind]}{day}-{uuid.uuid4().hex[:6]}"


def record_dir(kind: str, workspace: str) -> Path:
    return ws_mod.subdir(workspace, DIRS[kind])


def record_path(kind: str, record_id: str, workspace: str) -> Path:
    return record_dir(kind, workspace) / f"{record_id}.md"


def validate(kind: str, fm: dict) -> None:
    required, statuses, _ = SCHEMAS[kind]
    frontmatter.validate(fm, required, kind, statuses=statuses)


def read_record(kind: str, record_id: str, workspace: str = "", strict: bool = False):
    """Read one record. Returns None when absent or unparseable (unless strict).

    The record's `workspace` is always injected into `fm` so callers never have to
    thread the slug around, and legacy files that predate workspaces get backfilled.
    """
    slug = workspace or ws_mod.default_workspace()
    path = record_path(kind, record_id, slug)
    if not path.exists():
        if strict:
            raise NotFound(f"{kind}/{slug}/{record_id} not found")
        return None
    try:
        record = frontmatter.parse_file(path)
    except (BrainError, OSError) as exc:
        if strict:
            raise BrainError(f"{kind}/{slug}/{record_id}: {exc}")
        return None
    if record is None:
        return None
    record["id"] = str(record["fm"].get("id") or record_id)
    record["fm"].setdefault("id", record["id"])
    record["fm"]["workspace"] = slug
    record["kind"] = kind
    record["workspace"] = slug
    if strict:
        validate(kind, record["fm"])
    return record


def find_record(kind: str, record_id: str, workspaces=None):
    """Locate a record without knowing its workspace. Returns (slug, record) or None."""
    slugs = list(workspaces) if workspaces else ws_mod.all_slugs()
    for slug in slugs:
        record = read_record(kind, record_id, workspace=slug)
        if record:
            return slug, record
    return None


def write_record(kind: str, fm: dict, body: str, workspace: str = "",
                 validate_schema: bool = True, reindex: bool = True) -> Path:
    """Serialise, validate and atomically write one record, then reindex just it."""
    slug = workspace or str(fm.get("workspace") or ws_mod.default_workspace())
    fm = dict(fm)
    fm["workspace"] = slug
    fm.setdefault("id", new_id(kind))
    if validate_schema:
        validate(kind, fm)
    path = record_path(kind, str(fm["id"]), slug)
    _, _, order = SCHEMAS[kind]
    atomic_write(path, frontmatter.dumps(fm, order) + "\n" + body.rstrip("\n") + "\n")
    if reindex:
        index.reindex_doc(kind, slug, path, fm, body)
    return path


def update_record(kind: str, record: dict, workspace: str = "",
                  reindex: bool = True) -> Path:
    """Rewrite a record that was already read (preserves its original path/order)."""
    slug = workspace or record.get("workspace") or ws_mod.default_workspace()
    fm = dict(record["fm"])
    fm["workspace"] = slug
    validate(kind, fm)
    _, _, order = SCHEMAS[kind]
    path = record.get("path") or record_path(kind, str(fm["id"]), slug)
    atomic_write(path, frontmatter.dumps(fm, order) + "\n" + record["body"].rstrip("\n") + "\n")
    if reindex:
        index.reindex_doc(kind, slug, Path(path), fm, record["body"])
    return Path(path)


def move_record(kind: str, record: dict, to_workspace: str, from_workspace: str = "") -> Path:
    """Relocate a record between workspaces, updating its frontmatter.

    Used to correct a record that landed in the wrong scope — e.g. legacy claims that
    were filed as shared truth because nobody knew which project they belonged to.
    """
    origin = from_workspace or record.get("workspace") or ws_mod.default_workspace()
    fm = dict(record["fm"])
    fm["workspace"] = to_workspace
    if kind == "claims":
        fm["scope"] = "global" if to_workspace == ws_mod.const.GLOBAL_WORKSPACE else "workspace"
    path = write_record(kind, fm, record.get("body", ""), workspace=to_workspace)
    old = record_path(kind, str(fm.get("id") or record["id"]), origin)
    if old.exists() and old != path:
        old.unlink()
        index.remove(kind, str(fm.get("id") or record["id"]), origin)
    return path


def delete_record(kind: str, record_id: str, workspace: str = "") -> bool:
    slug = workspace or ws_mod.default_workspace()
    path = record_path(kind, record_id, slug)
    if not path.exists():
        return False
    path.unlink()
    index.remove(kind, record_id, slug)
    return True


def all_records(kind: str, workspaces=None, detail: bool = True):
    """Every record of a kind across the given workspaces (default: all)."""
    slugs = list(workspaces) if workspaces else ws_mod.all_slugs()
    out = []
    for slug in slugs:
        directory = record_dir(kind, slug)
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(GLOBS[kind])):
            record = read_record(kind, path.stem, workspace=slug)
            if record is None:
                continue
            if not detail:
                record.pop("raw", None)
            out.append(record)
    return sorted(out, key=lambda r: str(r["fm"].get("created") or ""))


def quarantine_path(path: Path) -> Path:
    from .paths import now

    target = VAULT / const.META_DIR / "quarantine"
    target.mkdir(parents=True, exist_ok=True)
    return target / f"{path.name}.{now().replace(':', '')}"


def repair_malformed(path: Path, kind: str = "claims", dry_run: bool = False) -> tuple:
    """Recover a record whose frontmatter was written without quoting.

    The old writer emitted `key: value` with no escaping, so any value containing a
    newline split into extra lines and made the whole block unparseable. Repair keeps
    only the keys the schema actually defines, folds every other line into the body as
    evidence (nothing is discarded), and quarantines the original.
    """
    from . import frontmatter as fm_mod

    try:
        text = read_text(path)
    except OSError as exc:
        return False, f"unreadable: {exc}"
    if not text.startswith("---"):
        return False, "does not start with a frontmatter block"

    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    block = lines[1:end] if end is not None else lines[1:]
    tail = lines[end + 1:] if end is not None else []

    known = set(SCHEMAS.get(kind, (None, None, ()))[2])
    kept, stray = [], []
    for line in block:
        key, sep, _ = line.partition(":")
        token = key.strip()
        if sep and token in known:
            kept.append(line)
        elif line.strip():
            stray.append(line)
    if not kept:
        return False, "no recognised schema keys found"
    if not stray:
        return False, "no stray lines to recover (malformed for another reason)"

    extras = stray + [line for line in tail if line.strip()]
    repaired = ("---\n" + "\n".join(kept).rstrip() + "\n---\n\n"
                + "\n".join(extras).strip() + "\n")
    try:
        parsed, body = fm_mod.parse(repaired)
        validate(kind, dict(parsed, id=parsed.get("id", path.stem)))
    except BrainError as exc:
        return False, f"repair would still be invalid: {exc}"

    detail = (f"recovered keys [{', '.join(parsed)}]; moved {len(stray)} stray line(s) "
              f"into the body")
    if dry_run:
        return True, "would " + detail
    backup = quarantine_path(path)
    original = text if text.endswith("\n") else text + "\n"
    atomic_write(backup, original)
    atomic_write(path, repaired)
    return True, detail + f"; original quarantined at {backup}"


def scan_problems(kinds=KINDS) -> list:
    """Report records that cannot be parsed or violate their schema."""
    problems = []
    for slug in ws_mod.all_slugs():
        for kind in kinds:
            directory = record_dir(kind, slug)
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob(GLOBS[kind])):
                rel = f"{kind}/{slug}/{path.stem}"
                try:
                    record = frontmatter.parse_file(path)
                except (BrainError, OSError) as exc:
                    problems.append(f"{rel}: {exc}")
                    continue
                if record is None:
                    problems.append(f"{rel}: empty or unreadable")
                    continue
                fm = dict(record["fm"])
                fm.setdefault("id", path.stem)
                try:
                    validate(kind, fm)
                except BrainError as exc:
                    problems.append(str(exc).replace(f"{kind}: ", f"{rel}: "))
                    continue
                if not frontmatter.roundtrip_ok(fm):
                    problems.append(f"{rel}: frontmatter does not round-trip")
    return problems


# ---- leases --------------------------------------------------------------

ACTIVE = "active"


def active_sessions(workspaces=None):
    return [s for s in all_records("sessions", workspaces) if s["fm"].get("status") == ACTIVE]


def split_files(value) -> list:
    """Normalise a files field, which may be a list, a comma string or empty."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = str(value).split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def build_locks(workspaces=None):
    """file -> {session_id, agent, project, workspace, expires, remaining_mins}.

    A lease counts only while the session is active *and* the lease timestamp is in
    the future, so a crashed agent cannot hold a file forever.
    """
    locks = {}
    for session in active_sessions(workspaces):
        targets = split_files(session["fm"].get("files"))
        if not targets:
            continue
        expires_at = parse_ts(session["fm"].get("lease_expires"))
        if expires_at is None:
            continue
        remaining = (expires_at - datetime.now(expires_at.tzinfo)).total_seconds()
        if remaining <= 0:
            continue
        for target in targets:
            locks[target] = {
                "session_id": session["id"],
                "agent": session["fm"].get("agent", "?"),
                "project": session["fm"].get("project", ""),
                "workspace": session["workspace"],
                "expires": session["fm"].get("lease_expires", ""),
                "remaining_mins": int(remaining // 60),
            }
    return locks


def check_files(files, workspaces=None, exclude_session: str = ""):
    """Return the subset of `files` already leased by a different live session."""
    locks = build_locks(workspaces)
    conflicts = []
    for target in split_files(files):
        holder = locks.get(target)
        if holder and holder["session_id"] != exclude_session:
            conflicts.append((target, holder))
    return conflicts


# ---- vault housekeeping --------------------------------------------------


def config(merge_defaults: bool = True) -> dict:
    from .paths import config_path, read_json

    stored = read_json(config_path(), {}) or {}
    if not merge_defaults:
        return stored
    merged = {k: (dict(v) if isinstance(v, dict) else v)
              for k, v in const.DEFAULT_CONFIG.items()}
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def save_config(cfg: dict) -> None:
    from .paths import config_path, write_json
    write_json(config_path(), cfg)


def ensure_dirs() -> None:
    for sub in const.WS_SUBDIRS:
        (VAULT / sub).mkdir(parents=True, exist_ok=True)
    ws_mod.ensure_all()
