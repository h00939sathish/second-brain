# -*- coding: utf-8 -*-
"""Scoped git commits.

Rules the previous implementation broke:
  * never `git add -A` — the vault tree is not the only thing moving in it
  * always pass explicit paths
  * always check the return code and surface it, so a broken repo is not silent
  * committing is policy (`vcs.auto_commit`), not an unconditional side effect
"""

import subprocess
from pathlib import Path

from .paths import VAULT


def _git(args, cwd=None):
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd or VAULT),
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def is_repo(path=None) -> bool:
    target = Path(path or VAULT)
    return (target / ".git").exists()


def status(paths=None) -> str:
    args = ["status", "--porcelain"]
    if paths:
        args += ["--", *[str(p) for p in paths]]
    return _git(args).stdout.strip()


def commit(message: str, paths=None, allow_empty: bool = False, quiet: bool = True,
           no_verify: bool = False):
    """Stage and commit explicit paths only.

    Returns (ok: bool, detail: str). `git add -A` is intentionally absent: if an
    agent is mid-edit elsewhere in the vault, that work must not be swept into a
    commit labelled as a brain bookkeeping action.
    """
    if not is_repo():
        return False, "not a git repository"

    targets = [str(Path(p)) for p in (paths or [])]
    if not targets:
        return False, "no paths given"

    add = _git(["add", "--", *targets])
    if add.returncode != 0:
        return False, f"git add failed: {add.stderr.strip() or add.stdout.strip()}"

    if not status(targets):
        return True, "nothing to commit"

    args = ["commit", "-m", message]
    if allow_empty:
        args.insert(1, "--allow-empty")
    if no_verify:
        args.insert(1, "--no-verify")
    result = _git(args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return False, f"git commit failed: {detail[0] if detail else 'unknown error'}"

    if not quiet:
        first = (result.stdout or "").strip().splitlines()
        print(first[0] if first else "committed")
    return True, "committed"


def log(limit: int = 10, paths=None):
    args = ["log", f"-{int(limit)}", "--oneline", "--no-decorate"]
    if paths:
        args += ["--", *[str(p) for p in paths]]
    return _git(args).stdout.strip().splitlines()


def current_branch(cwd=None) -> str:
    result = _git(["branch", "--show-current"], cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else ""


def head_commit(cwd=None) -> str:
    """Return HEAD commit hash (abbreviated 8 chars) or empty string."""
    result = _git(["rev-parse", "--short=8", "HEAD"], cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else ""


def changed_files(since_commit: str = "", cwd=None) -> list:
    """Return relative paths of files modified between since_commit and HEAD, plus uncommitted edits."""
    if not is_repo(cwd):
        return []
    files = set()
    # 1. Diffs between since_commit and HEAD
    if since_commit:
        res = _git(["diff", "--name-only", since_commit, "HEAD"], cwd=cwd)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                line = line.strip()
                if line:
                    files.add(line)
    # 2. Uncommitted modifications and staged changes
    res_wt = _git(["status", "--porcelain"], cwd=cwd)
    if res_wt.returncode == 0:
        for line in res_wt.stdout.splitlines():
            if len(line) > 3:
                path = line[3:].strip()
                if " -> " in path:
                    path = path.split(" -> ")[1].strip()
                files.add(path)
    return sorted(files)
