# -*- coding: utf-8 -*-
"""Workspace registry and auto-detection.

A workspace is a named slice of the vault bound to a directory on disk. Everything
a workspace produces (claims, specs, tasks, sessions, context notes) lives under
`workspaces/<slug>/`, so work on JARVIS can never collide with work on TITAN.

Detection order, first hit wins:
  1. explicit `--workspace` / tool argument
  2. $SECOND_BRAIN_WORKSPACE
  3. `.brain-workspace` marker file in cwd or any parent
  4. `git config brain.workspace` in cwd
  5. longest registered workspace path that is a prefix of cwd
  6. `global`
"""

import os
import re
import subprocess
from pathlib import Path

from . import const
from .paths import (VAULT, read_json, read_text, workspaces_path, workspaces_root,
                    write_json, atomic_write)

_CACHE = {}


def score_detail(text: str, slug: str) -> tuple:
    """(distinct name hits, distinct keyword hits) for `slug` in `text`.

    Presence, not frequency: a long record that says 'titan' five times is not five
    times more TITAN than one that says it once, and frequency counting made verbose
    environment notes look project-specific.
    """
    haystack = str(text or "").lower()
    info = entry(slug)
    name = str(info.get("name") or "")
    names = {slug, slug.replace("-", " ")}
    if name:
        names |= {name.lower(), slugify(name), slugify(name).replace("-", " ")}
    names |= {str(a).lower() for a in (info.get("aliases") or [])}
    names = {n for n in names if n and len(n) > 2}
    keywords = {str(k).lower() for k in (info.get("keywords") or [])}
    # A name that is a substring of a keyword (or vice versa) must not count twice.
    keyword_hits = {k for k in keywords if k in haystack and k not in names}
    return (sum(1 for n in names if n in haystack), len(keyword_hits))


def score_text(text: str, slug: str) -> int:
    """How strongly `text` indicates workspace `slug`. Names beat topical keywords."""
    names_hit, keywords_hit = score_detail(text, slug)
    return 3 * names_hit + keywords_hit


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return slug or const.GLOBAL_WORKSPACE


def _default_registry() -> dict:
    return {
        "version": 2,
        "default": const.GLOBAL_WORKSPACE,
        "workspaces": {
            const.GLOBAL_WORKSPACE: {
                "path": str(VAULT),
                "description": "Cross-project truth. Included in every workspace's recall.",
                "aliases": ["all", "shared"],
            }
        },
    }


def load_registry(reload: bool = False) -> dict:
    if not reload and "reg" in _CACHE:
        return _CACHE["reg"]
    data = read_json(workspaces_path())
    if not isinstance(data, dict) or "workspaces" not in data:
        data = _default_registry()
        data["workspaces"] = {const.GLOBAL_WORKSPACE: _default_registry()["workspaces"][const.GLOBAL_WORKSPACE]}
    data.setdefault("default", const.GLOBAL_WORKSPACE)
    for slug, entry in list(data["workspaces"].items()):
        if not isinstance(entry, dict):
            data["workspaces"][slug] = {"path": str(entry)}
    _CACHE["reg"] = data
    return data


def save_registry(data: dict) -> None:
    _CACHE.pop("reg", None)
    write_json(workspaces_path(), data)


def all_slugs() -> list:
    return sorted(load_registry()["workspaces"].keys())


def default_workspace() -> str:
    return load_registry().get("default") or const.GLOBAL_WORKSPACE


def exists(slug: str) -> bool:
    return slug in load_registry()["workspaces"]


def entry(slug: str) -> dict:
    return load_registry()["workspaces"].get(slug, {})


def resolve_alias(name: str) -> str:
    """Accept a slug, a display name, or a registered alias."""
    if not name:
        return ""
    reg = load_registry()["workspaces"]
    wanted = slugify(name)
    if wanted in reg:
        return wanted
    lowered = str(name).strip().lower()
    for slug, data in reg.items():
        names = [slug, str(data.get("name", "")).lower(), slugify(data.get("name", ""))]
        names += [str(a).lower() for a in data.get("aliases", []) or []]
        if lowered in names or slugify(lowered) in names:
            return slug
    return wanted


def _terms(values) -> list:
    """Normalise `"a,b"`, `["a", "b"]` and repeated flags into a clean list."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out = []
    for item in values:
        out += [part.strip() for part in str(item).split(",") if part.strip()]
    return out


def register(name: str, path: str = "", description: str = "", aliases=None,
             make_default: bool = False, display_name: str = "",
             keywords=None) -> str:
    """Register a workspace. Idempotent: re-registering updates the path/description."""
    slug = resolve_alias(name) if name else ""
    if not slug:
        raise ValueError("workspace name is required")
    reg = load_registry(reload=True)
    data = reg["workspaces"].setdefault(slug, {})
    data["name"] = display_name or name
    data["path"] = str(Path(path).expanduser().resolve()) if path else data.get("path", "")
    if description:
        data["description"] = description
    if aliases:
        merged = {str(a).lower() for a in (data.get("aliases") or [])}
        merged |= {str(a).lower() for a in aliases}
        data["aliases"] = sorted(merged)
    incoming_kw = _terms(keywords)
    if incoming_kw:
        merged_kw = {str(k).lower() for k in (data.get("keywords") or [])}
        merged_kw |= {k.lower() for k in incoming_kw}
        data["keywords"] = sorted(merged_kw)
    if make_default:
        reg["default"] = slug
    save_registry(reg)
    ensure_workspace_dirs(slug)
    return slug


def needles(slug: str) -> set:
    """Strings that indicate a record belongs to this workspace.

    `keywords` are extra terms beyond the name and aliases, which is what lets a
    legacy claim about 'CRYPTO-004' or 'Dukascopy' be recognised as TITAN work even
    though it never spells the project name.
    """
    info = entry(slug)
    out = {slug, slug.replace("-", " ")}
    name = str(info.get("name") or "")
    if name:
        out |= {name.lower(), slugify(name), slugify(name).replace("-", " ")}
    out |= {str(a).lower() for a in (info.get("aliases") or [])}
    out |= {str(k).lower() for k in (info.get("keywords") or [])}
    return {n for n in out if n and len(n) > 2}


def set_identity(slug: str, display_name: str = "", aliases=(), keywords=(),
                 replace: bool = False) -> dict:
    """Set a workspace's display name and aliases without changing its slug.

    Deterministic migration of pre-workspace records depends on this: legacy files say
    `project: Project TITAN`, so 'project titan' has to resolve to the `titan` slug
    rather than creating a second workspace.
    """
    reg = load_registry(reload=True)
    slug = resolve_alias(slug) if slug in reg["workspaces"] else slugify(slug)
    data = reg["workspaces"].setdefault(slug, {})
    if display_name:
        data["name"] = display_name
    # `replace=True` is required to *narrow* an identity: a generic alias like 'brain'
    # silently matches prose from every project, so the merge-only form can never undo
    # a bad choice once it has been made.
    merged = set() if replace else {str(a).lower() for a in (data.get("aliases") or [])}
    merged |= {str(a).lower() for a in aliases}
    if display_name:
        merged.add(display_name.lower())
        merged.add(slugify(display_name))
    merged.add(slug)
    data["aliases"] = sorted(a for a in merged if a)
    # Accept both `--keywords a,b` and repeated `--keywords a --keywords b`, like tags.
    incoming = _terms(keywords)
    if incoming or replace:
        merged_kw = set() if replace else {str(k).lower() for k in (data.get("keywords") or [])}
        merged_kw |= {k.lower() for k in incoming}
        data["keywords"] = sorted(k for k in merged_kw if k)
    save_registry(reg)
    return {"slug": slug, "name": data.get("name", slug), "aliases": data["aliases"],
            "keywords": data.get("keywords", [])}


def merge(source: str, target: str) -> tuple:
    """Move every record out of one workspace into another, then drop the source.

    Used to clean up slugs that were auto-registered from legacy `project:` strings
    before their aliases were known (e.g. `project-titan` -> `titan`).
    """
    src, dst = resolve_alias(source), resolve_alias(target)
    if src == dst:
        return dst, []
    if not exists(src):
        raise ValueError(f"workspace '{src}' is not registered")
    if not exists(dst):
        register(dst, description=f"merged from {src}")
    ensure_workspace_dirs(dst)
    moved = []
    for kind in const.WS_SUBDIRS:
        origin = subdir(src, kind)
        if not origin.is_dir():
            continue
        for path in sorted(origin.glob("*.md")):
            destination = subdir(dst, kind) / path.name
            if destination.exists():
                moved.append(f"skipped {kind}/{path.name} (already in {dst})")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.rename(destination)
            moved.append(f"{kind}/{path.name} -> {dst}")
    reg = load_registry(reload=True)
    reg["workspaces"].pop(src, None)
    if reg.get("default") == src:
        reg["default"] = const.GLOBAL_WORKSPACE
    save_registry(reg)
    return dst, moved


def unregister(name: str) -> str:
    slug = resolve_alias(name)
    reg = load_registry(reload=True)
    if slug in reg["workspaces"]:
        del reg["workspaces"][slug]
        if reg.get("default") == slug:
            reg["default"] = const.GLOBAL_WORKSPACE
        save_registry(reg)
    return slug


def workspace_dir(slug: str) -> Path:
    return workspaces_root() / slug


def subdir(slug: str, kind: str) -> Path:
    """`kind` is one of claims/specs/tasks/sessions/context/context/archive/logs."""
    return workspace_dir(slug) / kind


def ensure_workspace_dirs(slug: str) -> Path:
    root = workspace_dir(slug)
    for sub in const.WS_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    # A README pins the directory into git and tells a curious human what it is.
    readme = root / "README.md"
    if not readme.exists():
        info = entry(slug)
        atomic_write(
            readme,
            f"# Workspace: {info.get('name', slug)}\n\n"
            f"Scope: `{slug}`  \n"
            f"Root: `{info.get('path') or '(unbound)'}`  \n"
            f"{info.get('description', '')}\n\n"
            "Everything an agent writes while working in this workspace lands here:\n\n"
            "- `claims/`   — durable, verifiable facts (the knowledge base)\n"
            "- `specs/`    — upstream design intent\n"
            "- `tasks/`    — kanban cards\n"
            "- `sessions/` — who worked, on what, holding which file leases\n"
            "- `context/`  — short-lived scratchpad notes, promoted to claims when proven\n"
        )
    return root


def ensure_all() -> None:
    for slug in all_slugs():
        ensure_workspace_dirs(slug)


# ---- detection -----------------------------------------------------------


def _from_marker(start: Path):
    for parent in [start, *start.parents]:
        marker = parent / const.WORKSPACE_MARKER
        if marker.is_file():
            name = marker.read_text(encoding="utf-8", errors="replace").strip()
            if name:
                return resolve_alias(name.splitlines()[0])
        if parent == VAULT.parent:
            break
    return ""


def _from_git(start: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "config", "brain.workspace"],
            cwd=str(start), capture_output=True, text=True, timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return resolve_alias(proc.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _from_path(start: Path) -> str:
    """Longest registered path that prefixes cwd wins, so nested repos resolve exactly."""
    try:
        resolved = start.resolve()
    except OSError:
        return ""
    best, best_len = "", -1
    for slug, data in load_registry()["workspaces"].items():
        raw = data.get("path")
        if not raw:
            continue
        try:
            base = Path(raw).resolve()
        except OSError:
            continue
        if resolved == base or base in resolved.parents:
            if len(str(base)) > best_len:
                best, best_len = slug, len(str(base))
    return best


def detect(cwd=None, explicit: str = "") -> str:
    """Return the workspace slug that applies to `cwd`, or the default."""
    if explicit:
        return resolve_alias(explicit)
    env = os.environ.get("SECOND_BRAIN_WORKSPACE")
    if env:
        return resolve_alias(env)
    start = Path(cwd or Path.cwd())
    return (
        _from_marker(start)
        or _from_git(start)
        or _from_path(start)
        or default_workspace()
    )


def describe(cwd=None, explicit: str = "") -> dict:
    slug = detect(cwd=cwd, explicit=explicit)
    info = dict(entry(slug))
    info["slug"] = slug
    info["dir"] = str(workspace_dir(slug))
    info["is_default"] = slug == default_workspace()
    return info


POINTER_MARK = "## Second Brain (shared agent memory)"


def pointer_block(slug: str) -> str:
    return f"""
---

{POINTER_MARK}

This project is bound to the `{slug}` workspace of the shared brain at `{VAULT}`.
Any agent working here should use it: the workspace is detected from the cwd, so no
configuration is needed.

```bash
brain whoami                 # confirm which workspace you are in
brain brief                  # your context: leases, board, recent notes, top claims
brain start --agent <you> --files <paths you will write>   # leases are enforced
brain recall "..."           # knowledge other agents recorded for this project
brain post "..."             # something the other agents should know right now
brain claim "..." --source <path>    # anything durable you proved
brain end <session-id> --summary "..." --test-status "pytest: N passed"
```

Full protocol: `brain bootstrap`, or read `{VAULT}/AGENTS.md`.
"""


def add_pointer(slug: str, directory: str, skill: bool = True,
                dry_run: bool = False) -> list:
    """Leave a discoverable pointer in the project so a new agent finds the brain.

    Prefers an existing AGENTS.md (the emerging cross-agent convention), falls back to
    CLAUDE.md, and only creates BRAIN.md when neither exists. Never rewrites the file:
    the block is appended, delimited by a heading, and skipped if already present.

    Also drops `.agents/skills/second-brain/SKILL.md` in the project. Markdown pointers
    are passive — a hosted agent with no local config never reads them unless its model
    happens to open the file. A skill is *discovered* by the client itself, so this is
    what makes an agent we have never configured work the brain on its first task.
    """
    root = Path(directory).expanduser()
    if not root.is_dir():
        return [f"pointer skipped ({root} is not a directory)"]
    actions = []
    if skill:
        from . import agents  # local import: agents imports this module
        agents.install_skill(actions, dry_run=dry_run, project_root=str(root))
    block = pointer_block(slug)
    touched = 0
    # Every convention file that exists gets the block: agents disagree about which one
    # they read (Claude Code reads CLAUDE.md, most others look for AGENTS.md).
    for name in ("AGENTS.md", "CLAUDE.md"):
        target = root / name
        if not target.is_file():
            continue
        try:
            text = read_text(target)
        except OSError as exc:
            actions.append(f"pointer skipped ({name}: {exc})")
            continue
        if POINTER_MARK in text:
            actions.append(f"pointer: {name} already references the brain")
            touched += 1
            continue
        if dry_run:
            actions.append(f"pointer: would append to {name}")
            touched += 1
            continue
        atomic_write(target, text.rstrip("\n") + "\n" + block)
        actions.append(f"pointer: appended to {name}")
        touched += 1
    if touched:
        return actions
    target = root / "BRAIN.md"
    if target.is_file() and POINTER_MARK in read_text(target):
        actions.append("pointer: BRAIN.md already references the brain")
        return actions
    if dry_run:
        actions.append("pointer: would create BRAIN.md")
        return actions
    atomic_write(target, f"# Agent notes — {root.name}\n" + block)
    actions.append("pointer: created BRAIN.md")
    return actions


def bind_directory(slug: str, directory: str, write_marker: bool = True,
                   set_git_config: bool = False, pointer: bool = False,
                   skill: bool = False) -> list:
    """Bind a project directory to a workspace so agents need no flags there.

    Writes `<dir>/.brain-workspace` (read at detection time) and optionally sets
    `git config brain.workspace` for agents that resolve it that way.
    """
    actions = []
    slug = resolve_alias(slug) if slug else detect(directory)
    if not exists(slug):
        register(slug, path=directory)
        actions.append(f"registered workspace '{slug}'")
    root = ensure_workspace_dirs(slug)
    actions.append(f"workspace dir: {root}")
    directory = str(Path(directory).expanduser().resolve())
    if write_marker:
        try:
            atomic_write(Path(directory) / const.WORKSPACE_MARKER, f"{slug}\n")
            actions.append(f"marker: {directory}/{const.WORKSPACE_MARKER}")
        except OSError as exc:
            actions.append(f"marker skipped ({exc})")
    if set_git_config:
        try:
            subprocess.run(["git", "config", "brain.workspace", slug],
                           cwd=directory, capture_output=True, timeout=3)
            actions.append(f"git config brain.workspace = {slug}")
        except (OSError, subprocess.SubprocessError):
            actions.append("git config skipped")
    if pointer or skill:
        actions += add_pointer(slug, directory, skill=skill)
    actions += exclude_locally(directory)
    return actions


def exclude_locally(directory: str) -> list:
    """Keep the marker file out of `git status` without touching the tracked .gitignore.

    `.git/info/exclude` is machine-local and untracked, which is exactly the right
    place for state that says "this checkout belongs to workspace X". Adding it to the
    project's .gitignore would create a diff in a repository we do not own.
    """
    root = Path(directory).expanduser()
    git_dir = root / ".git"
    if git_dir.is_file():  # worktree: `.git` is a pointer file
        try:
            git_dir = Path(read_text(git_dir).split("gitdir:", 1)[1].strip())
        except (IndexError, OSError):
            return []
    if not git_dir.is_dir():
        return []
    exclude = git_dir / "info" / "exclude"
    # `brain setup` writes a generated SKILL.md into the project so the agent clients
    # discover the brain on their own. It is machine-local state, so keep it out of
    # `git status` here rather than editing a .gitignore we do not own.
    wanted = [const.WORKSPACE_MARKER, "BRAIN.md",
              ".agents/skills/second-brain/", ".claude/skills/second-brain/"]
    try:
        existing = read_text(exclude) if exclude.exists() else ""
    except OSError:
        return []
    missing = [w for w in wanted if w not in existing.split()]
    if not missing:
        return ["git exclude: marker already ignored"]
    exclude.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(exclude, existing.rstrip("\n") + "\n# second brain\n"
                 + "\n".join(missing) + "\n")
    return [f"git exclude: ignored {', '.join(missing)}"]


# ---- scoping helpers -----------------------------------------------------


def read_scope(slug: str) -> list:
    """Workspaces a read from `slug` sees: itself plus the global workspace."""
    slugs = [slug]
    if slug != const.GLOBAL_WORKSPACE:
        slugs.append(const.GLOBAL_WORKSPACE)
    return slugs


def write_scope(slug: str, scope: str = "") -> str:
    """Where a record is written. `scope=global` promotes to shared truth."""
    if str(scope).strip().lower() == "global":
        return const.GLOBAL_WORKSPACE
    return slug
