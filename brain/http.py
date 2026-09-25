# -*- coding: utf-8 -*-
"""Mission Control API.

Differences from the previous server worth calling out:

* no fabricated telemetry. `daemon_active` comes from the daemon heartbeat, log
  timestamps come from the log file's mtime (they used to be `now()` at page load),
  and `tokenCost`/`hasWarning` are gone rather than hardcoded per task.
* threading server instead of a serialised one, bound to localhost by default.
* refusals are returned as HTTP 409 with the reason, so the UI shows "this move needs
  review evidence" instead of silently succeeding.
* every list endpoint accepts `?workspace=`; `/api/workspaces` describes the scopes.
"""

import json
import mimetypes
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import (agents, board, const, coordination, daemon, deliberation, dispatch, goals,
               knowledge, l0, maintenance, squad, store, workspaces as ws_mod)
from .errors import (BrainError, CycleDetectedError, DeliberationGate, LeaseConflict, NotFound,
                    ReviewGate)
from .paths import VAULT, now, stdout_utf8

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("BRAIN_HOST", "127.0.0.1")
DIST_DIR = VAULT / "dist"
VERBOSE = os.environ.get("BRAIN_HTTP_VERBOSE") == "1"


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"SecondBrain/{__import__('brain').__version__}"

    # ---- plumbing ----

    def log_message(self, fmt, *args):
        if VERBOSE:
            sys.stderr.write("[http] " + (fmt % args) + "\n")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _send(self, payload, status=200, content_type="application/json; charset=utf-8"):
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, indent=2).encode("utf-8")
        else:
            body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc, status=400):
        self._send({"error": str(exc), "type": type(exc).__name__}, status=status)

    def _body(self):
        length = _int(self.headers.get("Content-Length"), 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError as exc:
            raise BrainError(f"invalid JSON body: {exc}")

    def _query(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _workspace(self, query=None):
        query = query if query is not None else self._query()
        return query.get("workspace", "")

    def _all_workspaces(self, query=None):
        query = query if query is not None else self._query()
        return str(query.get("all", "")).lower() in ("1", "true", "yes")

    # ---- GET ----

    def do_GET(self):
        path = urlparse(self.path).path
        query = self._query()
        try:
            if path == "/api/health":
                return self._send({"ok": True, "vault": str(VAULT), "time": now()})
            if path == "/agent/bootstrap":
                return self._send(
                    agents.bootstrap_brief(agent=query.get("agent", ""),
                                           workspace=query.get("workspace", "")),
                    content_type="text/plain; charset=utf-8")
            if path == "/api/brief":
                return self._send(l0.read(query.get("workspace", "")),
                                  content_type="text/plain; charset=utf-8")
            if path == "/api/workspaces":
                return self._send(self._workspaces())
            if path == "/api/status":
                return self._send(self._status())
            if path == "/api/runs":
                return self._send(dispatch.all_run_records(self._workspace(query)))
            if path == "/api/tasks":
                return self._send(self._tasks(query))
            if path == "/api/specs":
                return self._send(self._specs(query))
            if path == "/api/goals":
                return self._send(self._goals(query))
            if path == "/api/claims":
                return self._send(self._claims(query))
            if path == "/api/recall":
                return self._send(self._recall(query))
            if path == "/api/graph":
                return self._send(self._graph(query))
            if path == "/api/leases":
                return self._send(self._leases(query))
            if path == "/api/handoffs":
                return self._send(self._handoffs(query))
            if path == "/api/context":
                return self._send(self._context(query))
            if path == "/api/notes":
                return self._send(self._notes(query))
            if path == "/api/squad":
                return self._send(squad.squad_status(self._workspace(query)))
            if path == "/api/deliberation":
                task_id = query.get("task") or query.get("task_id", "")
                if not task_id:
                    return self._error(BrainError("task parameter is required"), status=400)
                return self._send(deliberation.get_room(task_id, self._workspace(query)))
            if path == "/api/logs":
                return self._send(self._logs(query))
        except BrainError as exc:
            return self._error(exc, 409 if isinstance(exc, (LeaseConflict, ReviewGate, CycleDetectedError, DeliberationGate)) else 400)
        except Exception as exc:  # never take the dashboard down
            return self._error(exc, 500)

        if path.startswith("/api/"):
            return self._send({"error": f"unknown endpoint {path}"}, status=404)
        return self._static(path)

    # ---- payload builders ----

    def _workspaces(self):
        return [ws_mod.describe(explicit=slug) for slug in ws_mod.all_slugs()]

    def _status(self):
        # Reads only: atomic writes mean no lock is needed, and holding one here
        # would serialise the whole dashboard behind a single slow request.
        stats = knowledge.stats()
        unreviewed = len(knowledge.unreviewed())
        tasks = board.list_tasks(all_workspaces=True)
        sessions = coordination.list_sessions(all_workspaces=True, active_only=True)
        locks = store.build_locks()
        dstatus = daemon.daemon_status()
        budget = l0.budget_state()
        return {
            "status": "healthy",
            "vault": str(VAULT),
            "version": __import__("brain").__version__,
            "workspaces": ws_mod.all_slugs(),
            "default_workspace": ws_mod.default_workspace(),
            "claims_total": stats["total"],
            "claims_active": stats["by_status"].get("active", 0),
            "unreviewed_claims": unreviewed,
            "claims_by_status": stats["by_status"],
            "claims_by_workspace": stats["by_workspace"],
            "tasks_total": len(tasks),
            "tasks_active": len([t for t in tasks
                                 if t["fm"].get("status") in ("planning", "running", "review")]),
            "specs_total": len(board.list_specs(all_workspaces=True)),
            "sessions_active": len(sessions),
            "file_locks": len(locks),
            "l0_bytes": budget["bytes"],
            "l0_budget": budget["budget"],
            "daemon": dstatus,
            "daemon_active": dstatus["active"],
            "index": {"engine": "sqlite_fts5", "bm25": True},
        }

    def _tasks(self, query):
        slug = query.get("workspace", "")
        tasks = board.list_tasks(workspace=slug, project=query.get("project", ""),
                                 status=query.get("status", ""),
                                 all_workspaces=self._all_workspaces(query))
        runs = {r.get("task_id"): r for r in dispatch.all_run_records(slug)}
        out = []
        for task in tasks:
            fm = task["fm"]
            meta = board.agent_meta(fm.get("agent"))
            tags = []
            if fm.get("project") and str(fm["project"]) not in tags:
                tags.append(str(fm["project"]))
            if fm.get("workspace") and str(fm["workspace"]) not in tags:
                tags.append(str(fm["workspace"]))
            if fm.get("tags"):
                raw = fm["tags"]
                for tag in (raw if isinstance(raw, list) else str(raw).split(",")):
                    tag = str(tag).strip()
                    if tag and tag not in tags:
                        tags.append(tag)
            run = runs.get(task["id"]) or {}
            entry = {
                "id": task["id"],
                "title": fm.get("title", "Untitled task"),
                "status": fm.get("status", "backlog"),
                "assignee": meta,
                "tags": tags,
                "specLink": fm.get("spec_id", ""),
                "description": task["body"].strip(),
                "createdAt": fm.get("created", ""),
                "updatedAt": fm.get("updated", ""),
                "workspace": task["workspace"],
                "agent": board.resolve_agent(fm.get("agent")),
                "runState": ("running" if run.get("returncode") is None and run else
                             "finished" if run else "none"),
            }
            if isinstance(fm.get("files"), list) and fm["files"]:
                entry["files"] = fm["files"]
            out.append(entry)
        return out

    def _specs(self, query):
        specs = board.list_specs(workspace=query.get("workspace", ""),
                                 project=query.get("project", ""),
                                 all_workspaces=self._all_workspaces(query))
        return [{
            "id": spec["id"],
            "title": spec["fm"].get("title", ""),
            "project": spec["fm"].get("project", ""),
            "workspace": spec["workspace"],
            "phases": (spec["fm"].get("phases") or []) if isinstance(
                spec["fm"].get("phases"), list) else [
                p.strip() for p in str(spec["fm"].get("phases") or "").split(",") if p.strip()],
            "created": spec["fm"].get("created", ""),
            "body": spec["body"],
        } for spec in specs]

    def _goals(self, query):
        specs = self._specs(query)
        return {"goals": specs, "count": len(specs)}

    def _claims(self, query):
        shown, withheld = knowledge.recall(
            query=query.get("q", ""), workspace=query.get("workspace", ""),
            tag=query.get("tag", ""), status=query.get("status", ""),
            include_withheld=str(query.get("withheld", "")).lower() in ("1", "true"),
            all_workspaces=self._all_workspaces(query),
            limit=_int(query.get("limit")),
        )
        return {"claims": shown, "withheld": withheld, "count": len(shown) + len(withheld)}

    def _recall(self, query):
        shown, withheld = knowledge.recall(
            query=query.get("q", ""), workspace=query.get("workspace", ""),
            tag=query.get("tag", ""), status=query.get("status", ""),
            all_workspaces=self._all_workspaces(query), limit=_int(query.get("limit")),
        )
        return {"matches": shown, "withheld": withheld}

    def _graph(self, query):
        slug = query.get("workspace", "")
        nodes = []
        specs = board.list_specs(workspace=slug, all_workspaces=self._all_workspaces(query))
        tasks = board.list_tasks(workspace=slug, all_workspaces=self._all_workspaces(query))
        specs_by_id = {s["id"]: s for s in specs}
        for i, spec in enumerate(specs):
            nodes.append({"id": spec["id"], "label": _lab(spec["fm"].get("title")),
                          "type": "spec", "x": 60 + i * 260, "y": 60,
                          "status": "in_progress", "connections": [],
                          "meta": {"project": spec["fm"].get("project", ""),
                                   "workspace": spec["workspace"]}})
        for i, task in enumerate(tasks):
            links = []
            spec_id = task["fm"].get("spec_id")
            if spec_id and spec_id in specs_by_id:
                links.append(spec_id)
                for node in nodes:
                    if node["id"] == spec_id:
                        node["connections"].append(task["id"])
            nodes.append({
                "id": task["id"], "label": _lab(task["fm"].get("title")), "type": "task",
                "x": 60 + (i % 6) * 220, "y": 220 + (i // 6) * 130,
                "status": {"done": "complete", "review": "in_progress",
                           "running": "in_progress"}.get(task["fm"].get("status"), "pending"),
                "connections": links,
                "meta": {"agent": str(task["fm"].get("agent") or ""),
                         "workspace": task["workspace"]},
            })
        claims, _ = knowledge.recall(workspace=slug, all_workspaces=self._all_workspaces(query),
                                     limit=24)
        for i, claim in enumerate(claims):
            nodes.append({
                "id": claim["id"], "label": _lab(claim["claim"]), "type": "claim",
                "x": 60 + (i % 6) * 220, "y": 560 + (i // 6) * 110,
                "status": "complete", "connections": [],
                "meta": {"workspace": claim["workspace"], "source": claim["source"],
                         "confidence": str(claim["confidence"])},
            })
        return nodes

    def _leases(self, query):
        leases = []
        for target, info in store.build_locks().items():
            meta = board.agent_meta(info["agent"])
            leases.append({
                "id": f"lease-{info['session_id']}-{abs(hash(target)) % 10000}",
                "file": target,
                "holder": meta["name"],
                "holderCode": meta["code"],
                "holderColor": meta["color"],
                "workspace": info["workspace"],
                "duration": f"{info['remaining_mins']}m remaining",
            })
        return leases

    def _handoffs(self, query):
        out = []
        for session in coordination.handoffs(workspace=query.get("workspace", ""), limit=10):
            fm = session["fm"]
            source = board.agent_meta(fm.get("agent"))
            target = board.agent_meta(fm.get("target_agent"))
            ended = str(fm.get("ended") or "")
            out.append({
                "id": f"h-{session['id']}",
                "from": source["name"], "fromCode": source["code"],
                "to": target["name"], "toCode": target["code"],
                "task_id": fm.get("task_id", ""),
                "workspace": session["workspace"],
                "testStatus": fm.get("test_status", ""),
                "timeAgo": _human(ended) if ended else "in progress",
            })
        return out

    def _context(self, query):
        out = []
        for note in coordination.read_notes(workspace=query.get("workspace", ""),
                                            limit=_int(query.get("limit"), 25),
                                            all_workspaces=self._all_workspaces(query)):
            meta = board.agent_meta(note.get("agent"))
            out.append({"id": note["id"], "source": meta["name"], "color": meta["color"],
                        "text": (note.get("body") or "").strip(),
                        "workspace": note.get("workspace", ""),
                        "project": note.get("project", ""),
                        "timestamp": _human(note.get("created"))})
        return out

    def _notes(self, query):
        notes = coordination.read_notes(
            query=query.get("q", ""),
            workspace=self._workspace(query),
            project=query.get("project", ""),
            agent=query.get("agent", ""),
            topic=query.get("topic", ""),
            limit=_int(query.get("limit"), 50),
            all_workspaces=self._all_workspaces(query),
        )
        out = []
        for note in notes:
            meta = board.agent_meta(note.get("agent"))
            out.append({
                "id": note["id"],
                "source": meta["name"],
                "agent": note.get("agent", ""),
                "color": meta["color"],
                "topic": note.get("topic", ""),
                "text": (note.get("body") or "").strip(),
                "workspace": note.get("workspace", ""),
                "project": note.get("project", ""),
                "created": note.get("created", ""),
                "timestamp": _human(note.get("created")),
            })
        return out

    def _logs(self, query):
        entries = []
        slugs = [query["workspace"]] if query.get("workspace") else ws_mod.all_slugs()
        for slug in slugs:
            directory = dispatch.run_dir(slug)
            if not directory.is_dir():
                continue
            files = sorted(directory.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            for path in files[:4]:
                try:
                    stat = path.stat()
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                stamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc) \
                    .strftime("%H:%M:%S")
                for line in text.splitlines()[-const.MAX_DISPATCH_LOG_LINES:]:
                    if not line.strip():
                        continue
                    upper = line.upper()
                    level = ("ERR" if "ERROR" in upper or "TRACEBACK" in upper else
                             "WARN" if "WARN" in upper else
                             "OK" if "DONE" in upper or "PASSED" in upper else "INFO")
                    entries.append({
                        "id": f"log-{slug}-{path.stem}-{len(entries)}",
                        "timestamp": stamp,
                        "level": level,
                        "tag": f"[{path.stem}]",
                        "sourceColor": board.agent_meta(
                            (dispatch.read_run_record(slug, path.stem) or {}).get("agent"))["color"],
                        "message": line[:200],
                        "workspace": slug,
                    })
        return entries

    # ---- POST / DELETE ----

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/tasks":
                result = board.create_task(
                    title=body.get("title", ""), workspace=body.get("workspace", ""),
                    project=body.get("project", ""), spec_id=body.get("spec_id", ""),
                    agent=body.get("agent", ""), phase=body.get("phase", ""),
                    files=body.get("files", ""))
                return self._send({"success": True, **{k: str(v) for k, v in result.items()}})
            if path.startswith("/api/tasks/") and path.endswith("/move"):
                task_id = path.split("/")[3]
                result = board.move(task_id, body.get("status", ""),
                                    workspace=body.get("workspace", ""),
                                    agent=body.get("agent", ""), notes=body.get("notes", ""),
                                    force=bool(body.get("force")),
                                    tests=body.get("tests", ""))
                return self._send({"success": True, **result})
            if path.startswith("/api/tasks/") and path.endswith("/terminate"):
                task_id = path.split("/")[3]
                return self._send({"success": True, **self._terminate(task_id, body)})
            if path == "/api/dispatch":
                result = dispatch.dispatch(body.get("task_id", ""), agent=body.get("agent", ""),
                                           workspace=body.get("workspace", ""),
                                           tab=bool(body.get("tab")))
                status = 200 if result.get("ok") else 409
                return self._send(result, status=status)
            if path == "/api/auto-cycle":
                result = daemon.auto_cycle(workspace=body.get("workspace", ""),
                                           project=body.get("project", ""),
                                           tab=bool(body.get("tab")))
                return self._send(result, status=200 if result.get("ok") else 409)
            if path == "/api/claims":
                return self._send({"success": True, **knowledge.add(
                    text=body.get("text", ""), workspace=body.get("workspace", ""),
                    source=body.get("source", ""), tags=body.get("tags", ""),
                    confidence=body.get("confidence", 0.9), scope=body.get("scope", ""))})
            if path == "/api/notes":
                return self._send({"success": True, **coordination.post(
                    text=body.get("text", ""), workspace=body.get("workspace", ""),
                    project=body.get("project", ""), tags=body.get("tags", ""),
                    agent=body.get("agent", "operator"), topic=body.get("topic", ""))})
            if path == "/api/squad":
                return self._send({"success": True, **squad.save_squad(
                    body, body.get("workspace") or self._workspace(self._query()))})
            if path == "/api/squad/role":
                return self._send({"success": True, **squad.set_role(
                    role=body.get("role", ""),
                    agent=body.get("agent", ""),
                    workspace=body.get("workspace") or self._workspace(self._query()))})
            if path == "/api/deliberation/open":
                return self._send({"success": True, **deliberation.open_room(
                    task_id=body.get("task_id") or body.get("task", ""),
                    workspace=body.get("workspace") or self._workspace(self._query()),
                    risk=body.get("risk", "normal"),
                    mode=body.get("mode", "normal"),
                    participants=body.get("participants"),
                    domains=body.get("domains"),
                    max_rounds=_int(body.get("max_rounds"), 3),
                    actor=body.get("actor", "control-plane"))})
            if path == "/api/deliberation/post":
                return self._send({"success": True, **deliberation.post_message(
                    task_id=body.get("task_id") or body.get("task", ""),
                    sender=body.get("sender") or body.get("agent", "operator"),
                    msg_type=body.get("type", "MESSAGE"),
                    body=body.get("body") or body.get("text", ""),
                    recipient=body.get("recipient", ""),
                    severity=body.get("severity", "medium"),
                    references=body.get("references"),
                    workspace=body.get("workspace") or self._workspace(self._query()))})
            if path == "/api/deliberation/adjudicate":
                result = deliberation.adjudicate(
                    task_id=body.get("task_id") or body.get("task", ""),
                    workspace=body.get("workspace") or self._workspace(self._query()),
                    actor=body.get("actor", "control-plane"),
                    force=bool(body.get("force")))
                return self._send(result, status=200 if result.get("ok") else 409)
            if path == "/api/sweep":
                changed = maintenance.sweep(workspace=body.get("workspace", ""),
                                           commit=bool(body.get("commit")), quiet=True)
                return self._send({"success": True, "flagged": len(changed),
                                   "items": [{"id": i, "why": w} for i, w in changed]})
            if path == "/api/goals":
                result = goals.propose_goal(
                    goal=body.get("goal", ""),
                    tasks=body.get("tasks", []),
                    spec=body.get("spec"),
                    workspace=body.get("workspace", ""),
                    project=body.get("project", ""),
                    actor=body.get("actor", "agent:jarvis"),
                )
                return self._send(result)
            if path == "/api/setup":
                return self._send({"success": True,
                                   "actions": agents.configure(dry_run=bool(body.get("dry_run")))})
        except (ReviewGate, LeaseConflict, CycleDetectedError, DeliberationGate) as exc:
            return self._error(exc, 409)
        except NotFound as exc:
            return self._error(exc, 404)
        except BrainError as exc:
            return self._error(exc, 400)
        except Exception as exc:
            return self._error(exc, 500)
        return self._send({"error": f"unknown endpoint {path}"}, status=404)

    def _terminate(self, task_id, body):
        slug = body.get("workspace", "")
        found = board.get_task(task_id, slug)
        if not found:
            raise NotFound(f"task {task_id} not found")
        slug = found[0]
        for session in coordination.list_sessions(workspace=slug, active_only=True):
            if str(session["fm"].get("task_id")) == task_id:
                coordination.end(session["id"], summary="terminated by operator",
                                 workspace=slug)
        return board.move(task_id, "done", workspace=slug, agent="operator",
                          notes="terminated by operator")

    def do_DELETE(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/tasks/"):
                task_id = path.split("/")[3]
                slug = self._query().get("workspace", "")
                found = board.get_task(task_id, slug)
                if not found:
                    return self._error(NotFound(f"task {task_id} not found"), 404)
                slug = found[0]
                path_on_disk = found[1]["path"]
                store.delete_record("tasks", task_id, workspace=slug)
                from . import vcs
                vcs.commit(f"task {task_id}: deleted by operator", paths=[path_on_disk])
                return self._send({"success": True, "deleted": task_id, "workspace": slug})
        except BrainError as exc:
            return self._error(exc, 400)
        return self._send({"error": f"unknown endpoint {path}"}, status=404)

    # ---- static ----

    def _static(self, path):
        if not DIST_DIR.exists():
            return self._send(
                "Second Brain API is running, but there is no built dashboard.\n"
                "Run `npm install && npm run build`, or `npm run dev` for the dev server.\n"
                "Universal agent entry point: GET /agent/bootstrap\n",
                content_type="text/plain; charset=utf-8")
        target = DIST_DIR / (path.lstrip("/") or "index.html")
        if not target.is_file():
            target = DIST_DIR / "index.html"
        mime, _ = mimetypes.guess_type(str(target))
        try:
            content = target.read_bytes()
        except OSError as exc:
            return self._error(exc, 500)
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _lab(text, limit: int = 42) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _human(stamp: str) -> str:
    from .paths import time_ago
    return time_ago(stamp) if stamp else ""


def main(port: int = PORT, host: str = HOST) -> int:
    stdout_utf8()
    l0.write("")
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        # A raw traceback here is unhelpful: the usual cause is another service on the
        # port (a project's own API, or a second brain), and the fix is a different port.
        print(f"could not listen on {host}:{port} — {exc}\n"
              f"something else is already using that port; pick another with "
              f"`brain serve --port <n>`", file=sys.stderr)
        return 1
    print("=" * 62)
    print(f"  Second Brain — Mission Control  http://{host}:{port}")
    print(f"  vault: {VAULT}")
    print(f"  agents reach it with:  curl -s http://{host}:{port}/agent/bootstrap")
    print("=" * 62)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0
