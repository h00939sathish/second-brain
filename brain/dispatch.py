# -*- coding: utf-8 -*-
"""Portable background dispatch of agent CLIs.

The previous implementation could only run on Windows: it built `pwsh.exe -Command`
strings, piped into `.cmd` shims, and hardcoded `D:\\projects\\Project TITAN`. On this
Linux host `pwsh`, `wt.exe` and every `.cmd` shim are absent while `codex`, `opencode`,
`claude` and `agy` are all present natively — so the whole autonomy layer was dead code.

Now every CLI is resolved with `shutil.which` from the same table on every platform,
prompts are fed on stdin (no shell quoting, no `Get-Content`), and the child inherits a
sanitised environment that pins the correct vault and workspace.
"""

import json
import os
import shutil
import subprocess

from . import board, coordination, store, workspaces as ws_mod
from .errors import AgentUnavailable, NotFound
from .paths import VAULT, atomic_write, logs_dir, now, read_json
from . import agents

# Terminals in preference order. Each entry builds the argv around a command string.
TERMINALS = (
    ("kitty", lambda title, script: ["kitty", "--title", title, "-e", "bash", "-lc", script]),
    ("foot", lambda title, script: ["foot", "--title", title, "bash", "-lc", script]),
    ("alacritty", lambda title, script: ["alacritty", "-t", title, "-e", "bash", "-lc", script]),
    ("ghostty", lambda title, script: ["ghostty", "-e", "bash", "-lc", script]),
    ("wezterm", lambda title, script: ["wezterm", "start", "--", "bash", "-lc", script]),
    ("gnome-terminal", lambda title, script: ["gnome-terminal", "--title", title, "--", "bash", "-lc", script]),
    ("x-terminal-emulator", lambda title, script: ["x-terminal-emulator", "-e", "bash", "-lc", script]),
    ("wt.exe", lambda title, script: ["wt.exe", "-w", "0", "new-tab", "bash", "-lc", script]),
)


def cli_argv(agent: str, prompt_file=None):
    """argv for one headless run of `agent`, or None when the CLI is missing.

    The prompt goes in on stdin, so no shell, no quoting and no `.cmd` shim issue.
    """
    canonical = board.resolve_agent(agent)
    spec = const_cli(canonical)
    if spec is None:
        return None
    binary = agents.find_cli(canonical)
    if binary is None:
        return None
    return [binary, *spec["args"]]


def const_cli(agent: str):
    from . import const
    return const.AGENT_CLIS.get(board.resolve_agent(agent))


def run_dir(workspace: str):
    return logs_dir(workspace)


def run_record_path(workspace: str, task_id: str):
    return run_dir(workspace) / f"{task_id}.run.json"


def write_run_record(workspace: str, task_id: str, data: dict) -> None:
    atomic_write(run_record_path(workspace, task_id),
                 json.dumps(data, indent=2, default=str) + "\n")


def read_run_record(workspace: str, task_id: str):
    return read_json(run_record_path(workspace, task_id), None)


def all_run_records(workspace: str = "") -> list:
    runs = []
    slugs = [workspace] if workspace else ws_mod.all_slugs()
    for slug in slugs:
        directory = run_dir(slug)
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.run.json")):
            data = read_json(path, None)
            if data:
                data.setdefault("workspace", slug)
                runs.append(data)
    return sorted(runs, key=lambda r: str(r.get("started") or ""), reverse=True)


def resolve_cwd(workspace: str) -> str:
    """Run the agent inside the workspace's own project directory when we know it."""
    info = ws_mod.entry(workspace)
    path = str(info.get("path") or "")
    if path and os.path.isdir(path):
        return path
    return str(VAULT)


def build_prompt(task: dict, workspace: str = "", agent: str = "") -> str:
    """The brief an agent receives when the board hands it a card."""
    fm = task["fm"]
    slug = workspace or task.get("workspace") or ws_mod.default_workspace()
    canonical = board.resolve_agent(agent or fm.get("agent")) or "opencode"
    role = board.role_of(canonical)

    spec_text = ""
    spec_id = str(fm.get("spec_id") or "")
    if spec_id:
        found = store.find_record("specs", spec_id, [slug])
        if found:
            spec_text = f"\n## Linked spec [[{spec_id}]]\n{found[1]['body']}\n"

    files = fm.get("files") or []
    files_arg = ",".join(files) if isinstance(files, (list, tuple)) else str(files)

    steps = {
        "planner": [
            f"brain start --agent {canonical} --task-id {task['id']} --task \"planning {task['id']}\"",
            "draft the invariants and phases, then:",
            f"brain spec-create --title \"...\" --project {fm.get('project') or slug} --phases \"a,b,c\"",
            f"brain task-create --title \"...\" --spec <spec-id> --agent opencode",
            f"brain move {task['id']} --status running --agent opencode",
        ],
        "builder": [
            f"brain start --agent {canonical} --task-id {task['id']} --files {files_arg}",
            "implement, then run the tests",
            f"brain end <session-id> --summary \"...\" --target-agent agy --test-status \"pytest: N passed\"",
        ],
        "reviewer": [
            f"brain start --agent {canonical} --task-id {task['id']}",
            "audit the diff against the spec, run the suite",
            f"brain post \"verification report\" --project {fm.get('project') or slug}",
            f"brain move {task['id']} --status done --tests \"pytest: N passed\"",
        ],
    }.get(role, [f"brain start --agent {canonical} --task-id {task['id']}"])

    return f"""You have been dispatched by the Second Brain board.

Task:    {task['id']} — {fm.get('title')}
Status:  [{fm.get('status')}]        Role: {role} ({canonical})
Project: {fm.get('project') or slug}  Workspace: {slug}
Files:   {files_arg or '(none declared)'}
{spec_text}
## Protocol

Your session was already opened for you; it holds this card's file leases, so other
agents will refuse to touch those files until you finish. Do not edit files outside
your lease — reserve more with `brain reserve <session-id> --files ...`.

Next actions:

""" + "\n".join(f"  {i}. {step}" for i, step in enumerate(steps, 1)) + f"""

Notes for other agents: `brain post "..."` (visible immediately) or
`brain claim "..." --source "..."` if you proved something durable. Do not edit the
vault by hand; use `brain`.

Begin now.
"""


def dispatch(task_id: str, agent: str = "", workspace: str = "", tab: bool = False,
             timeout: int = 0, wait: bool = False, extra_prompt: str = ""):
    """Start one agent on one card. Returns a result dict (never raises for a missing CLI)."""
    found = board.get_task(task_id, workspace)
    if not found:
        raise NotFound(f"task {task_id} not found")
    slug, task = found
    canonical = board.resolve_agent(agent or task["fm"].get("agent")) or "opencode"

    caller = board.resolve_agent(os.environ.get("BRAIN_AGENT", "").strip())
    from . import topology
    allowed, reason = topology.can_route(caller, canonical, workspace=slug)
    if not allowed:
        raise topology.TopologyError(
            f"dispatch denied by topology: {reason} — name the seat you are routing "
            f"from (BRAIN_AGENT=<seat>) or carry a grant (`brain bypass-grant`)")

    argv = cli_argv(canonical)
    if argv is None:
        return {
            "ok": False, "agent": canonical, "task_id": task_id, "workspace": slug,
            "detail": f"{canonical} CLI not found on PATH (install it, or use "
                      f"`brain bootstrap` from the agent you do have)",
        }

    prompt = build_prompt(task, workspace=slug, agent=canonical)
    if extra_prompt:
        prompt = prompt + "\n\n" + extra_prompt

    directory = run_dir(slug)
    directory.mkdir(parents=True, exist_ok=True)
    prompt_file = directory / f"{task_id}.prompt.txt"
    log_file = directory / f"{task_id}.log"
    atomic_write(prompt_file, prompt)

    # Auto-session: identical re-dispatch must not pile up sessions.
    existing = [s for s in coordination.list_sessions(workspace=slug, active_only=True)
                if str(s["fm"].get("task_id")) == task_id]
    if existing:
        session_id = existing[0]["id"]
    else:
        session = coordination.start(
            agent=canonical, workspace=slug, project=str(task["fm"].get("project") or slug),
            task=str(task["fm"].get("title") or ""), task_id=task_id,
            files=task["fm"].get("files"), force=True,
        )
        session_id = session["id"]

    env = agents.child_env(slug)
    started = now()
    if tab:
        launch = open_tab(f"{canonical}: {task_id}", argv, prompt_file, directory)
        write_run_record(slug, task_id, {
            "task_id": task_id, "workspace": slug, "agent": canonical,
            "session_id": session_id, "mode": "tab", "started": started,
            "log": str(log_file), "prompt": str(prompt_file), "detail": launch,
        })
        return {"ok": True, "agent": canonical, "task_id": task_id, "workspace": slug,
                "session_id": session_id, "mode": "tab", "detail": launch}

    try:
        with open(prompt_file, "rb") as stdin, open(log_file, "ab") as stdout:
            stdout.write(f"\n===== {started} {canonical} on {task_id} =====\n".encode())
            stdout.flush()
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kwargs["start_new_session"] = True
            if wait:
                completed = subprocess.run(
                    argv, stdin=stdin, stdout=stdout, stderr=subprocess.STDOUT,
                    cwd=resolve_cwd(slug), env=env, timeout=timeout or None, **kwargs,
                )
                result = {"pid": None, "returncode": completed.returncode}
            else:
                proc = subprocess.Popen(
                    argv, stdin=stdin, stdout=stdout, stderr=subprocess.STDOUT,
                    cwd=resolve_cwd(slug), env=env, **kwargs,
                )
                result = {"pid": proc.pid, "returncode": None}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "agent": canonical, "task_id": task_id, "workspace": slug,
                "session_id": session_id, "detail": f"failed to start {canonical}: {exc}"}

    write_run_record(slug, task_id, {
        "task_id": task_id, "workspace": slug, "agent": canonical,
        "session_id": session_id, "mode": "background", "started": started,
        "pid": result["pid"], "returncode": result["returncode"],
        "log": str(log_file), "prompt": str(prompt_file),
        "cwd": resolve_cwd(slug), "finished": now() if result["returncode"] is not None else "",
    })
    if result["returncode"] is not None:
        from . import evidence
        evidence.record_receipt(
            task_id=task_id,
            command=" ".join(argv),
            exit_code=result["returncode"],
            workspace=slug,
            session_id=session_id,
            cwd=resolve_cwd(slug),
            transcript_log=str(log_file),
        )
    return {"ok": True, "agent": canonical, "task_id": task_id, "workspace": slug,
            "session_id": session_id, "mode": "background", "pid": result["pid"],
            "log": str(log_file)}


def get_transcript(session_or_task_id: str, workspace: str = "", tail: int = 0, grep: str = "") -> dict:
    """Read and optionally filter the execution transcript for a session or task."""
    import re
    slug = workspace or ws_mod.default_workspace()
    directory = run_dir(slug)

    target_path = None
    if (directory / f"{session_or_task_id}.log").exists():
        target_path = directory / f"{session_or_task_id}.log"
    else:
        for run in all_run_records(slug):
            if run.get("session_id") == session_or_task_id or run.get("task_id") == session_or_task_id:
                candidate = Path(run.get("log", ""))
                if candidate.exists():
                    target_path = candidate
                    break

    if not target_path or not target_path.exists():
        raise NotFound(f"no transcript found for '{session_or_task_id}' in workspace '{slug}'")

    raw_text = target_path.read_text(encoding="utf-8", errors="replace")
    clean_text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw_text)
    lines = clean_text.splitlines()

    if grep:
        pattern = re.compile(grep, re.IGNORECASE)
        lines = [l for l in lines if pattern.search(l)]

    if tail and tail > 0:
        lines = lines[-tail:]

    return {
        "id": session_or_task_id,
        "path": str(target_path),
        "total_lines": len(lines),
        "lines": lines,
        "content": "\n".join(lines),
    }


def open_tab(title: str, argv, prompt_file, log_dir) -> str:
    """Open the agent in a terminal window so a human can watch it work."""
    script = f"exec {shlex_quote(argv)} < {shlex_quote(str(prompt_file))} 2>&1 | tee -a {shlex_quote(str(log_dir / 'stream.log'))}"
    for name, builder in TERMINALS:
        binary = shutil.which(name)
        if not binary:
            continue
        try:
            subprocess.Popen(builder(title, script),
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"opened in {name}"
        except (OSError, subprocess.SubprocessError):
            continue
    return ("no supported terminal found (tried kitty, foot, alacritty, ghostty, wezterm, "
            "gnome-terminal); ran headless instead")


def shlex_quote(value) -> str:
    import shlex
    if isinstance(value, (list, tuple)):
        return " ".join(shlex.quote(str(v)) for v in value)
    return shlex.quote(str(value))
