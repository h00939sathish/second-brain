# -*- coding: utf-8 -*-
"""Board watcher + auto-cycle.

Two loop bugs from the previous implementation are fixed here:

* `auto-cycle` used to pick `running[0]` every call, "dispatch" it, and leave the
  status untouched — so every invocation spawned another identical agent process.
  Now a card with a live session or a live process is reported, not dispatched.
* the circuit breaker existed only inside the daemon loop. It now lives in
  `should_dispatch()` so the CLI, the HTTP API and the MCP tool all get it.
"""

import json
import os
import time

from . import board, coordination, dispatch, workspaces as ws_mod
from .paths import VAULT, atomic_write, heartbeat_path, now, read_json

MAX_ATTEMPTS = 3


def pid_alive(pid) -> bool:
    """Best-effort liveness check, so a finished run is not treated as in-flight."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import subprocess
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True, timeout=5).stdout
            return str(pid) in out
        except (OSError, Exception):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def in_flight(task_id: str, workspace: str = "") -> dict:
    """An existing live run for this card: an active session, or a live process."""
    record = dispatch.read_run_record(workspace, task_id)
    if record:
        if record.get("mode") == "background" and pid_alive(record.get("pid")):
            return {"kind": "process", "pid": record.get("pid"), "agent": record.get("agent")}
        if record.get("mode") == "tab" and not record.get("finished"):
            # A watched tab cannot be polled; a live session is the better signal.
            pass
    sessions = [s for s in coordination.list_sessions(workspace=workspace, active_only=True)
                if str(s["fm"].get("task_id")) == task_id]
    if sessions:
        session = sessions[0]
        expires = session["fm"].get("lease_expires") or ""
        return {"kind": "session", "session_id": session["id"],
                "agent": session["fm"].get("agent"), "lease_expires": expires}
    return {}


def _attempts_path(workspace: str):
    from .paths import workspaces_root
    return workspaces_root() / (workspace or "global") / "logs" / ".dispatch_attempts.json"


def load_attempts(workspace: str) -> dict:
    return read_json(_attempts_path(workspace), {}) or {}


def save_attempts(workspace: str, attempts: dict) -> None:
    atomic_write(_attempts_path(workspace), json.dumps(attempts, indent=2) + "\n")


def should_dispatch(task_id: str, status: str, workspace: str = "", max_attempts: int = MAX_ATTEMPTS):
    """(ok, detail) — respects both the in-flight guard and the circuit breaker."""
    live = in_flight(task_id, workspace)
    if live:
        who = live.get("agent") or "an agent"
        how = live.get("session_id") or f"pid {live.get('pid')}"
        return False, f"already in flight: {who} ({live['kind']} {how})"
    attempts = load_attempts(workspace)
    entry = attempts.get(task_id) or {}
    same_status = entry.get("status") == status
    count = int(entry.get("count", 0)) + 1 if same_status else 1
    attempts[task_id] = {"status": status, "count": count, "last": now()}
    save_attempts(workspace, attempts)
    if count > max_attempts:
        return False, (f"circuit breaker: {count - 1} attempts already spent on "
                       f"[{status}] without progress (reset the card or dispatch manually)")
    return True, f"attempt {count}/{max_attempts}"


def clear_attempts(task_id: str, workspace: str = "") -> None:
    attempts = load_attempts(workspace)
    if task_id in attempts:
        del attempts[task_id]
        save_attempts(workspace, attempts)


def auto_cycle(workspace: str = "", project: str = "", tab: bool = False,
               max_attempts: int = MAX_ATTEMPTS, cfg=None) -> dict:
    """Dispatch the highest-priority actionable card, exactly once."""
    step = board.actionable(workspace=workspace, project=project)
    if not step:
        return {"ok": True, "action": "idle", "detail": "board is clear"}

    slug = step["workspace"]
    if step["from_backlog"]:
        try:
            board.move(step["task_id"], "planning", workspace=slug,
                       notes="picked up by auto-cycle")
        except Exception as exc:  # keep the loop alive; report instead of dying
            return {"ok": False, "action": "move", "task_id": step["task_id"],
                    "detail": f"could not advance from backlog: {exc}"}
        step["status"] = "planning"
        step["agent"] = "codex"

    ok, why = should_dispatch(step["task_id"], step["status"], slug, max_attempts)
    if not ok:
        return {"ok": True, "action": "skip", "task_id": step["task_id"],
                "status": step["status"], "agent": step["agent"], "detail": why}

    result = dispatch.dispatch(step["task_id"], agent=step["agent"], workspace=slug, tab=tab)
    result.update({"action": "dispatch", "status": step["status"], "detail": why})
    if result.get("ok"):
        clear_attempts(step["task_id"], slug)
    return result


# ---- heartbeat -----------------------------------------------------------


def write_heartbeat(data: dict) -> None:
    atomic_write(heartbeat_path(), json.dumps(data, indent=2, default=str) + "\n")


def read_heartbeat() -> dict:
    return read_json(heartbeat_path(), {}) or {}


def daemon_status(stale_after: int = 90) -> dict:
    """Real daemon liveness, so /api/status never has to hardcode `true`."""
    data = read_heartbeat()
    if not data:
        return {"active": False, "detail": "never started"}
    try:
        age = time.time() - float(data.get("last_tick_epoch") or 0)
    except (TypeError, ValueError):
        age = 10 ** 9
    active = age <= stale_after and (pid_alive(data.get("pid")) or data.get("stopped"))
    if data.get("stopped"):
        return {"active": False, "detail": "stopped", **{k: data.get(k) for k in
                                                         ("pid", "interval", "ticks")}}
    return {
        "active": bool(active),
        "detail": f"last tick {int(age)}s ago" if age < 10 ** 8 else "stale",
        "pid": data.get("pid"),
        "interval": data.get("interval"),
        "ticks": data.get("ticks"),
        "age_seconds": int(age) if age < 10 ** 8 else None,
    }


def run(interval: int = 15, workspace: str = "", project: str = "",
        max_attempts: int = MAX_ATTEMPTS, once: bool = False, commit: bool = True,
        cfg=None) -> int:
    """Continuously drive the board. Ctrl-C stops cleanly."""
    interval = max(5, int(interval or 15))
    started = now()
    ticks = 0
    print("=" * 62)
    print("  SECOND BRAIN — autonomous board driver")
    print(f"  every {interval}s | workspace: {workspace or 'auto'} | project: {project or 'all'}")
    print(f"  vault: {VAULT}")
    print("=" * 62)

    def beat(**extra):
        write_heartbeat({"pid": os.getpid(), "started": started, "interval": interval,
                         "ticks": ticks, "last_tick": now(), "last_tick_epoch": time.time(),
                         "workspace": workspace or "auto", "project": project or "",
                         **extra})

    try:
        while True:
            ticks += 1
            try:
                result = auto_cycle(workspace=workspace, project=project,
                                    max_attempts=max_attempts, cfg=cfg)
            except Exception as exc:  # a daemon must survive a single bad card
                result = {"ok": False, "action": "error", "detail": str(exc)}
            stamp = now()[11:19]
            if result.get("action") == "dispatch" and result.get("ok"):
                print(f"[{stamp}] DISPATCH {result['task_id']} -> {result.get('agent')} "
                      f"({result.get('detail')}) log={result.get('log')}", flush=True)
                beat(last_task=result["task_id"], last_agent=result.get("agent"))
            elif result.get("action") in ("skip",):
                print(f"[{stamp}] SKIP {result.get('task_id')}: {result.get('detail')}", flush=True)
                beat(last_task=result.get("task_id"), last_action="skip")
            elif result.get("action") == "idle":
                print(f"[{stamp}] idle — board clear", flush=True)
                beat(last_action="idle")
            else:
                print(f"[{stamp}] {result.get('action')}: {result.get('detail')}", flush=True)
                beat(last_action=result.get("action", "unknown"))
            if once:
                beat(stopped=True)
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        write_heartbeat({**read_heartbeat(), "stopped": True, "last_tick_epoch": time.time()})
        print("\n[daemon] stopped gracefully")
        return 0
