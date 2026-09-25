# -*- coding: utf-8 -*-
"""Sweep: the only command allowed to mutate records without a human's intent.

Everything here is idempotent and reports what it touched. It used to run
`git add -A` plus `commit --allow-empty` at the end, which folded unrelated in-flight
agent edits into a bookkeeping commit; commits are now scoped to the files sweep
actually changed, and only when asked.
"""

from . import coordination, index, knowledge, l0, store, vcs, workspaces as ws_mod
from .paths import VAULT, now, parse_ts


def sweep(workspace: str = "", commit: bool = False, quiet: bool = False, cfg=None):
    """Expire stale sessions, archive old notes, flag stale claims, refresh L0."""
    cfg = cfg or store.config()
    changed = []
    touched_paths = []

    changed += coordination.expire_stale(workspace=workspace, cfg=cfg)
    for note_id, why in coordination.archive_old_notes(cfg=cfg):
        changed.append((note_id, why))
    changed += knowledge.invalidate_stale_claims(workspace=workspace)

    # A claim is only "reviewed" if someone actually ran `brain review`.
    unreviewed_after = int(cfg.get("sweep", {}).get("expire_unreviewed_after_days", 120))
    stale_marker = f"> sweep {now()[:10]}"
    for record in store.all_records("claims"):
        if record["fm"].get("status") != "active":
            continue
        reviewed = parse_ts(record["fm"].get("reviewed_at"))
        created = parse_ts(record["fm"].get("created"))
        if reviewed is None:
            age = (parse_ts(now()) - created).days if created else None
            label = "never reviewed" if age is None else f"never reviewed, {age}d old"
            changed.append((record["id"], f"active but {label}"))
            if age is not None and age > unreviewed_after and stale_marker not in record["body"]:
                record["body"] = record["body"].rstrip() + (
                    f"\n\n{stale_marker}: active {age}d with no review — re-check the source "
                    "or dispute it\n"
                )
                store.update_record("claims", record, workspace=record["workspace"])
                touched_paths.append(record["path"])
            continue
        age_days = (parse_ts(now()) - reviewed).days
        if age_days > unreviewed_after and stale_marker not in record["body"]:
            record["body"] = record["body"].rstrip() + (
                f"\n\n{stale_marker}: last reviewed {age_days}d ago — needs re-verification\n"
            )
            store.update_record("claims", record, workspace=record["workspace"])
            touched_paths.append(record["path"])
            changed.append((record["id"], f"stale ({age_days}d since review)"))

    index.sync()
    l0.write_all()

    if commit:
        # Scoped on purpose: only brain data directories, never the repo root, so an
        # agent mid-edit elsewhere in the vault is not swept into this commit.
        targets = [str(ws_mod.workspaces_root()), str(VAULT / "meta")]
        message = f"sweep {now()}: {len(changed)} items processed"
        ok, detail = vcs.commit(message, paths=targets)
        if not quiet:
            print(f"commit: {'ok' if ok else 'skipped'} — {detail}")

    if not quiet:
        if changed:
            print(f"sweep: {len(changed)} item(s) flagged")
            for record_id, why in changed:
                print(f"  {record_id}: {why}")
        else:
            print("sweep: nothing to flag")
    return changed


def sweep_summary() -> dict:
    return {
        "scanned": now(),
        "claims": knowledge.stats(),
    }
