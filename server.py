#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py - Second Brain Mission Control Backend API Server (v1.0).
Zero-dependency HTTP server bridging the React/Vite dashboard directly to engine.py.
"""
import json
import os
import sys
import mimetypes
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from types import SimpleNamespace

VAULT = Path(__file__).resolve().parent
sys.path.insert(0, str(VAULT))
import engine

PORT = int(os.environ.get("PORT", 8000))
DIST_DIR = VAULT / "dist"


def get_agent_meta(agent_str):
    agent_lower = (agent_str or "").lower()
    if "codex" in agent_lower:
        return {"code": "CX", "name": "Codex (Planner)", "color": "#a855f7"}
    elif "claude" in agent_lower:
        return {"code": "CL", "name": "Claude Code (Builder)", "color": "#f97316"}
    elif "antigravity" in agent_lower or "agy" in agent_lower:
        return {"code": "AG", "name": "Antigravity (Reviewer)", "color": "#06b6d4"}
    elif "opencode" in agent_lower:
        return {"code": "OC", "name": "opencode (Builder)", "color": "#10b981"}
    elif "hermes" in agent_lower:
        return {"code": "HE", "name": "Hermes (Scout)", "color": "#3b82f6"}
    return {"code": "AG", "name": agent_str or "Agent", "color": "#64748b"}


class SecondBrainHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _json_response(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            with engine.lock():
                claims = engine.all_claims()
                active_claims = [c for c in claims if c["fm"].get("status", "active") == "active"]
                tasks = engine.all_tasks()
                specs = engine.all_specs()
                sessions = engine.all_sessions()
                active_sessions = [s for s in sessions if s["fm"].get("status") == "active"]
                locks = engine.get_active_file_locks()
                l0_size = (VAULT / engine.META_DIR / engine.L0_NAME).stat().st_size if (VAULT / engine.META_DIR / engine.L0_NAME).exists() else 0

            return self._json_response({
                "status": "healthy",
                "daemon_active": True,
                "claims_total": len(claims),
                "claims_active": len(active_claims),
                "tasks_total": len(tasks),
                "tasks_active": len([t for t in tasks if t["fm"].get("status") in ("planning", "running", "review")]),
                "specs_total": len(specs),
                "sessions_active": len(active_sessions),
                "file_locks": len(locks),
                "l0_bytes": l0_size,
                "l0_budget": engine.L0_BUDGET,
            })

        elif path == "/api/tasks":
            with engine.lock():
                raw_tasks = engine.all_tasks()

            kanban_tasks = []
            for t in raw_tasks:
                fm = t["fm"]
                agent_meta = get_agent_meta(fm.get("agent", ""))
                tags = [tag.strip() for tag in (fm.get("tags") or "").split(",") if tag.strip()]
                if fm.get("project") and fm.get("project") not in tags:
                    tags.insert(0, fm.get("project"))

                kanban_tasks.append({
                    "id": t["id"],
                    "title": fm.get("title", "Untitled Task"),
                    "status": fm.get("status", "backlog"),
                    "assignee": agent_meta,
                    "tags": tags,
                    "specLink": fm.get("spec_id", ""),
                    "description": t["body"].strip(),
                    "tokenCost": 0.04,
                    "createdAt": fm.get("created", engine.now()),
                    "hasWarning": False,
                })
            return self._json_response(kanban_tasks)

        elif path == "/api/specs":
            with engine.lock():
                raw_specs = engine.all_specs()
            specs_list = []
            for s in raw_specs:
                fm = s["fm"]
                specs_list.append({
                    "id": s["id"],
                    "title": fm.get("title", ""),
                    "project": fm.get("project", ""),
                    "phases": [p.strip() for p in (fm.get("phases") or "").split(",") if p.strip()],
                    "created": fm.get("created", ""),
                    "body": s["body"],
                })
            return self._json_response(specs_list)

        elif path == "/api/claims":
            with engine.lock():
                raw_claims = engine.all_claims()
            claims_list = []
            for c in raw_claims:
                fm = c["fm"]
                claims_list.append({
                    "id": c["id"],
                    "claim": fm.get("claim", ""),
                    "status": fm.get("status", "active"),
                    "confidence": fm.get("confidence", 0.9),
                    "tags": [t.strip() for t in (fm.get("tags") or "").split(",") if t.strip()],
                    "source": fm.get("source", ""),
                    "body": c["body"],
                })
            return self._json_response(claims_list)

        elif path == "/api/graph":
            with engine.lock():
                specs = engine.all_specs()
                tasks = engine.all_tasks()
                claims = engine.all_claims()

            nodes = []
            for i, s in enumerate(specs):
                nodes.append({
                    "id": s["id"],
                    "label": s["fm"].get("title", s["id"]),
                    "type": "spec",
                    "x": 200 + (i * 150),
                    "y": 150,
                    "status": "in_progress",
                    "connections": [],
                    "meta": {"project": s["fm"].get("project", "")}
                })

            for i, t in enumerate(tasks):
                st = t["fm"].get("status", "backlog")
                node_st = "complete" if st == "done" else ("in_progress" if st in ("running", "review", "planning") else "pending")
                spec_id = t["fm"].get("spec_id", "")
                conns = [spec_id] if spec_id else []
                nodes.append({
                    "id": t["id"],
                    "label": t["fm"].get("title", t["id"]),
                    "type": "task",
                    "x": 150 + ((i % 4) * 160),
                    "y": 300 + ((i // 4) * 120),
                    "status": node_st,
                    "connections": conns,
                    "meta": {"agent": t["fm"].get("agent", ""), "status": st}
                })

            active_claims = [c for c in claims if c["fm"].get("status", "active") == "active"][:12]
            for i, c in enumerate(active_claims):
                nodes.append({
                    "id": c["id"],
                    "label": c["fm"].get("claim", c["id"])[:40] + "...",
                    "type": "claim",
                    "x": 100 + ((i % 4) * 180),
                    "y": 480 + ((i // 4) * 100),
                    "status": "complete",
                    "connections": [],
                    "meta": {"source": c["fm"].get("source", "")}
                })

            return self._json_response(nodes)

        elif path == "/api/leases":
            with engine.lock():
                locks = engine.get_active_file_locks()
            leases_list = []
            for fpath, info in locks.items():
                agent_meta = get_agent_meta(info["agent"])
                leases_list.append({
                    "id": f"lease-{info['session_id']}",
                    "file": fpath,
                    "holder": agent_meta["name"],
                    "holderCode": agent_meta["code"],
                    "holderColor": agent_meta["color"],
                    "duration": f"{info['remaining_mins']}m remaining",
                })
            return self._json_response(leases_list)

        elif path == "/api/handoffs":
            with engine.lock():
                sessions = engine.all_sessions()
            handoffs = []
            for s in sorted(sessions, key=lambda x: x["fm"].get("ended", ""), reverse=True)[:6]:
                fm = s["fm"]
                if fm.get("target_agent"):
                    from_meta = get_agent_meta(fm.get("agent", ""))
                    to_meta = get_agent_meta(fm.get("target_agent", ""))
                    handoffs.append({
                        "id": f"h-{s['id']}",
                        "from": from_meta["name"],
                        "fromCode": from_meta["code"],
                        "to": to_meta["name"],
                        "toCode": to_meta["code"],
                        "timeAgo": fm.get("ended", "")[11:16] if fm.get("ended") else "recently",
                    })
            return self._json_response(handoffs)

        elif path == "/api/context":
            with engine.lock():
                notes = engine.all_context_notes(include_archived=False)
            messages = []
            for n in sorted(notes, key=lambda x: x["fm"].get("created", ""), reverse=True)[:10]:
                fm = n["fm"]
                agent_meta = get_agent_meta(fm.get("agent", ""))
                messages.append({
                    "id": n["id"],
                    "source": agent_meta["name"],
                    "color": agent_meta["color"],
                    "text": n["body"].strip(),
                    "timestamp": fm.get("created", "")[11:19] if fm.get("created") else "now",
                })
            return self._json_response(messages)

        elif path == "/api/logs":
            log_dir = VAULT / engine.LOGS_DIR
            log_entries = []
            if log_dir.exists():
                for lf in sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                    lines = lf.read_text(encoding="utf-8", errors="replace").splitlines()
                    for line in lines[-20:]:
                        if not line.strip():
                            continue
                        level = "INFO"
                        if "ERROR" in line or "ERR" in line:
                            level = "ERR"
                        elif "WARN" in line:
                            level = "WARN"
                        elif "DISPATCH" in line or "COMPLETED" in line:
                            level = "OK"

                        log_entries.append({
                            "id": f"log-{abs(hash(line))}",
                            "timestamp": engine.now()[11:19],
                            "level": level,
                            "tag": f"[{lf.stem}]",
                            "sourceColor": "#a855f7" if "t-" in lf.stem else "#06b6d4",
                            "message": line[:150],
                        })
            return self._json_response(log_entries)

        # Serve static frontend files from dist
        if DIST_DIR.exists():
            clean_path = path.lstrip("/") or "index.html"
            target_file = DIST_DIR / clean_path
            if not target_file.exists() or target_file.is_dir():
                target_file = DIST_DIR / "index.html"

            mime, _ = mimetypes.guess_type(str(target_file))
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            content = target_file.read_bytes()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()

        if path == "/api/tasks":
            title = body.get("title", "")
            project = body.get("project", "")
            spec_id = body.get("spec_id", "")
            agent = body.get("agent", "")
            phase = body.get("phase", "")
            files = body.get("files", "")
            args = SimpleNamespace(title=title, project=project, spec=spec_id, agent=agent, phase=phase, files=files)
            with engine.lock():
                cfg = engine.load_config()
                code = engine.cmd_task_create(args, cfg)
            return self._json_response({"success": code == 0})

        elif path.startswith("/api/tasks/") and path.endswith("/move"):
            tid = path.split("/")[3]
            status = body.get("status", "")
            agent = body.get("agent", "")
            notes = body.get("notes", "")
            args = SimpleNamespace(id=tid, status=status, agent=agent, notes=notes)
            with engine.lock():
                cfg = engine.load_config()
                code = engine.cmd_task_move(args, cfg)
            return self._json_response({"success": code == 0})

        elif path.startswith("/api/tasks/") and path.endswith("/terminate"):
            tid = path.split("/")[3]
            with engine.lock():
                cfg = engine.load_config()
                sessions = engine.all_sessions()
                for s in sessions:
                    if s["fm"].get("status") == "active":
                        s_args = SimpleNamespace(id=s["id"], target="", branch="", summary="Terminated by Operator")
                        engine.cmd_session_end(s_args, cfg)
                args = SimpleNamespace(id=tid, status="done", agent="Operator", notes="Terminated by Operator")
                code = engine.cmd_task_move(args, cfg)
            return self._json_response({"success": code == 0, "status": "done"})

        elif path == "/api/dispatch":
            tid = body.get("task_id", "")
            agent = body.get("agent", "")
            with engine.lock():
                cfg = engine.load_config()
                t = engine.get_task(tid)
                if t:
                    st = t["fm"].get("status", "backlog")
                    if st in ("backlog", "planning"):
                        target_st = "running"
                        target_agent = agent or t["fm"].get("agent") or "opencode"
                        move_args = SimpleNamespace(id=tid, status=target_st, agent=target_agent, notes=f"Dispatched to {target_agent}")
                        engine.cmd_task_move(move_args, cfg)
                args = SimpleNamespace(id=tid, agent=agent, tab=False)
                code = engine.cmd_dispatch(args, cfg)
            return self._json_response({"success": code == 0, "status": "running"})

        elif path == "/api/auto-cycle":
            project = body.get("project", "")
            args = SimpleNamespace(project=project, tab=False)
            with engine.lock():
                cfg = engine.load_config()
                code = engine.cmd_auto_cycle(args, cfg)
            return self._json_response({"success": code == 0})

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/tasks/"):
            tid = path.split("/")[3]
            with engine.lock():
                tpath = engine.task_path(tid)
                if os.path.exists(tpath):
                    os.remove(tpath)
                    engine.reindex_all_search()
                    engine.git_commit(f"task {tid}: deleted by operator")
                    return self._json_response({"success": True, "deleted": tid})
                return self._json_response({"error": "Task not found"}, status=404)
        self.send_response(404)
        self.end_headers()


def main():
    server = HTTPServer(("0.0.0.0", PORT), SecondBrainHandler)
    print("=" * 50)
    print("  Second Brain Mission Control Server (v1.0)")
    print(f"  Listening on: http://localhost:{PORT}")
    print("=" * 50)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")


if __name__ == "__main__":
    main()
