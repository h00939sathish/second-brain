# -*- coding: utf-8 -*-
"""Test harness.

`paths.VAULT` is resolved at import time from $SECOND_BRAIN_VAULT, so the environment
must be pointed at a throwaway vault *before* `brain` is imported. Every test module
imports this harness first for that reason — the real vault is never touched.
"""

import io
import os
import shutil
import tempfile
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="brain-tests-"))
os.environ["SECOND_BRAIN_VAULT"] = str(_TMP)
os.environ.pop("BRAIN_BYPASS", None)
os.environ.pop("SECOND_BRAIN_WORKSPACE", None)

from brain import (agents, board, cli, const, coordination, dispatch, frontmatter,  # noqa: E402
                   index, knowledge, l0, maintenance, store, vcs, workspaces as ws_mod)
from brain import http  # noqa: E402
from brain.errors import BrainError, LeaseConflict, NotFound, ReviewGate  # noqa: E402
from brain.paths import VAULT  # noqa: E402

assert str(VAULT) == str(_TMP), "harness failed to redirect the vault"


def reset_vault():
    """Wipe and re-initialise the temp vault. Called once per test case."""
    for child in VAULT.iterdir():
        if child.name in (".git",):
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink()
    os.environ.pop("SECOND_BRAIN_WORKSPACE", None)
    ws_mod._CACHE.clear()
    run("init")


def run(*argv, expect=0):
    """Run the CLI in-process and return (code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    args = [str(a) for a in argv]
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli.main(args)
    if expect is not None and code != expect:
        raise AssertionError(
            f"brain {' '.join(args)} exited {code}, expected {expect}\n"
            f"stdout:\n{stdout.getvalue()}\nstderr:\n{stderr.getvalue()}"
        )
    return code, stdout.getvalue(), stderr.getvalue()


def fresh_workspace(prefix="test"):
    """Register an isolated workspace for one test and return its slug."""
    slug = f"{prefix}-{uuid.uuid4().hex[:6]}"
    path = _TMP / "projects" / slug
    path.mkdir(parents=True, exist_ok=True)
    ws_mod.register(slug, path=str(path), description="test workspace")
    ws_mod.ensure_workspace_dirs(slug)
    return slug


def cwd_workspace(tmpdir: Path, slug: str):
    """Bind a directory to a workspace and return it."""
    tmpdir.mkdir(parents=True, exist_ok=True)
    ws_mod.bind_directory(slug, str(tmpdir))
    return tmpdir
