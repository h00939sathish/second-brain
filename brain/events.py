# -*- coding: utf-8 -*-
"""Canonical append-only event stream for the Local Agent Control Plane.

The event log is the immutable historical source of truth.
Projections (Markdown files in tasks/, claims/, sessions/) are materialized views.
"""

import json
import os
from pathlib import Path

from . import const, workspaces as ws_mod
from .paths import now


def events_dir(workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    directory = ws_mod.subdir(slug, "events")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _seq_file(slug: str) -> Path:
    return events_dir(slug) / ".sequence"


def next_sequence(workspace: str = "") -> int:
    """Monotonically ascending sequence integer per workspace."""
    slug = workspace or ws_mod.default_workspace()
    path = _seq_file(slug)
    seq = 0
    if path.exists():
        try:
            seq = int(path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            seq = 0
    seq += 1
    try:
        path.write_text(str(seq) + "\n", encoding="utf-8")
    except OSError:
        pass
    return seq


def emit(event_type: str, stage: str = "AUTHORIZE", actor: str = "control-plane",
         workspace: str = "", task_id: str = "", execution_id: str = "",
         payload: dict = None) -> dict:
    """Record an immutable event to the append-only stream."""
    slug = workspace or ws_mod.default_workspace()
    if stage not in const.EVENT_STAGES:
        stage = "AUTHORIZE"

    seq = next_sequence(slug)
    ts = now()
    date_str = ts[:10]  # YYYY-MM-DD
    event_id = f"evt_{date_str.replace('-', '')}_{seq:06d}"

    record = {
        "event_id": event_id,
        "sequence": seq,
        "timestamp": ts,
        "workspace": slug,
        "schema_version": const.EVENT_SCHEMA_VERSION,
        "stage": stage,
        "actor": actor,
        "event_type": event_type,
        "execution_id": execution_id or "",
        "task_id": task_id or "",
        "payload": payload or {},
    }

    log_path = events_dir(slug) / f"{date_str}.jsonl"
    line = json.dumps(record, ensure_ascii=False) + "\n"

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except OSError:
        pass

    return record


def read_events(workspace: str = "", date: str = "", event_type: str = "",
                task_id: str = "", stage: str = "", actor: str = "",
                limit: int = 100, reverse: bool = False, oldest: bool = False,
                all_workspaces: bool = False) -> list:
    """Query the event stream with filtering and sequence ordering."""
    if oldest:
        reverse = False
    slugs = ws_mod.all_slugs() if all_workspaces else [workspace or ws_mod.default_workspace()]
    events = []

    for slug in slugs:
        edir = events_dir(slug)
        if not edir.is_dir():
            continue

        if date:
            files = [edir / f"{date}.jsonl"]
        else:
            files = sorted(edir.glob("*.jsonl"))

        for file_path in files:
            if not file_path.is_file():
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if event_type and item.get("event_type") != event_type:
                            continue
                        if task_id and item.get("task_id") != task_id:
                            continue
                        if stage and item.get("stage") != stage:
                            continue
                        if actor and item.get("actor") != actor:
                            continue

                        events.append(item)
            except OSError:
                continue

    events.sort(key=lambda e: (e.get("timestamp", ""), e.get("sequence", 0)), reverse=reverse)
    return events[:limit] if limit > 0 else events
