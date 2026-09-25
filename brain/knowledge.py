# -*- coding: utf-8 -*-
"""Claim lifecycle: the durable knowledge base.

Design decisions worth knowing:

* `reviewed_at` is **only** set by an explicit review. The previous implementation
  stamped it at creation, which laundered the freshness gate that `sweep` depends on
  — a claim could never look unreviewed after 120 days because it looked reviewed
  from birth.
* a claim's full text is never truncated. Values that contain newlines are JSON
  quoted by the frontmatter writer, so `claim` and `evidence` round-trip exactly.
* `scope=global` writes the claim into the shared workspace, which every workspace's
  recall includes. That is how a fact learned in JARVIS stays useful in TITAN.
"""

import re

from . import const, events, index, l0, store, vcs, workspaces as ws_mod
from .errors import BrainError, NotFound
from .paths import VAULT, now, parse_ts


# The exact strings the previous vault used for "no value here".
_EMPTY = ("", "none", "null", "(none)", "-")


def _clean(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in _EMPTY else text


def claim_text(record) -> str:
    return str(record["fm"].get("claim") or "").strip()


def evidence_text(record) -> str:
    """The evidence block is the claim body minus the generated boilerplate."""
    body = record.get("body") or ""
    match = re.search(r"\*\*Evidence:\*\*\s*(.*?)(?:\n\n|\Z)", body, re.S)
    if match:
        return match.group(1).strip()
    return body.strip()


# ---- writing -------------------------------------------------------------


def add(text: str, workspace: str = "", status: str = "active", confidence: float = 0.9,
        source: str = "", tags="", scope: str = "", evidence: str = "",
        verified_commit: str = "", depends_on="", cwd=None, maturity: str = "") -> dict:
    """Record a claim. `tags` may be a comma string or a sequence."""
    text = str(text or "").strip()
    if not text:
        raise BrainError("a claim needs text")
    if status not in const.STATUSES:
        raise BrainError(f"invalid claim status {status!r}")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise BrainError(f"confidence {confidence!r} is not a number")
    if not 0.0 <= confidence <= 1.0:
        raise BrainError(f"confidence {confidence} is outside 0..1")

    maturity = (maturity or "").strip().lower()
    if maturity and maturity not in const.CLAIM_MATURITIES:
        raise BrainError(f"invalid claim maturity {maturity!r}; choose from {', '.join(const.CLAIM_MATURITIES)}")

    slug = ws_mod.write_scope(workspace or ws_mod.default_workspace(), scope)
    tag_list = _as_tags(tags)
    record_id = store.new_id("claims")
    created = now()

    if not maturity:
        if slug == const.GLOBAL_WORKSPACE or scope == "global":
            maturity = "canonical"
        elif confidence >= 0.8 and verified_commit:
            maturity = "established"
        else:
            maturity = const.DEFAULT_CLAIM_MATURITY

    # Parse and normalize depends_on
    if isinstance(depends_on, (list, tuple)):
        dep_files = [str(f).strip() for f in depends_on if str(f).strip()]
    elif depends_on:
        dep_files = [f.strip() for f in str(depends_on).split(",") if f.strip()]
    else:
        src = _clean(source)
        if src and not src.startswith("http") and not src.startswith("context:") and " " not in src:
            dep_files = [src]
        else:
            dep_files = []

    # Auto-detect verified_commit if not supplied
    if not verified_commit:
        ws_info = ws_mod.entry(slug)
        repo_dir = cwd or (ws_info.get("path") if ws_info else None) or str(VAULT)
        verified_commit = vcs.head_commit(repo_dir) or vcs.head_commit() or ""

    fm = {
        "id": record_id,
        "claim": text,
        "status": status,
        "confidence": confidence,
        "maturity": maturity,
        "workspace": slug,
        "scope": "global" if slug == const.GLOBAL_WORKSPACE else "workspace",
        "created": created,
        # Deliberately empty: only review() may stamp this.
        "reviewed_at": "",
        "source": _clean(source),
        "tags": ",".join(tag_list),
        "verified_commit": verified_commit or "",
        "depends_on": dep_files,
    }
    body = [f"**Claim:** {text}", ""]
    body.append(f"**Evidence:** {evidence.strip() or _clean(source) or '(none attached)'}")
    if dep_files:
        body.append(f"**Depends on:** {', '.join(dep_files)}")
    if verified_commit:
        body.append(f"**Verified commit:** `{verified_commit}`")
    related = _related_ids(tag_list, exclusive=record_id)
    if related:
        body += ["", "**Related:** " + " ".join(f"[[{r}]]" for r in related)]
    body += ["", f"Created {created} in workspace `{slug}` [{maturity}]. "
                 "Run `brain review {id}` once the source has been checked.".replace("{id}", record_id)]
    path = store.write_record("claims", fm, "\n".join(body), workspace=slug)
    events.emit("CLAIM_CREATED", stage="AUTHORIZE", workspace=slug,
                payload={"id": record_id, "claim": text, "confidence": confidence,
                         "maturity": maturity,
                         "verified_commit": verified_commit, "depends_on": dep_files})
    return {"id": record_id, "workspace": slug, "path": str(path),
            "maturity": maturity,
            "verified_commit": verified_commit, "depends_on": dep_files}


def review(record_id: str, workspace: str = "", note: str = "") -> dict:
    """Mark a claim as reviewed now, which resets its staleness clock."""
    found = store.find_record("claims", record_id) if not workspace else \
        (workspace, store.read_record("claims", record_id, workspace, strict=True))
    if not found:
        raise NotFound(f"claim {record_id} not found")
    slug, record = found
    record["fm"]["reviewed_at"] = now()
    if note:
        record["body"] = record["body"].rstrip() + f"\n\n> Reviewed {now()}: {note}\n"
    path = store.update_record("claims", record, workspace=slug)
    return {"id": record_id, "workspace": slug, "path": str(path)}


def revalidate(record_id: str, note: str = "", workspace: str = "", verified_commit: str = "",
               cwd=None) -> dict:
    """Re-verify a claim against HEAD, restoring ACTIVE status and updating verified_commit."""
    found = store.find_record("claims", record_id) if not workspace else \
        (workspace, store.read_record("claims", record_id, workspace, strict=True))
    if not found:
        raise NotFound(f"claim {record_id} not found")
    slug, record = found

    ws_info = ws_mod.entry(slug)
    repo_path = cwd or (ws_info.get("path") if ws_info else None) or str(VAULT)
    new_commit = verified_commit or vcs.head_commit(repo_path) or vcs.head_commit()

    stamp_now = now()
    record["fm"]["status"] = "active"
    record["fm"]["reviewed_at"] = stamp_now
    if new_commit:
        record["fm"]["verified_commit"] = new_commit

    old_maturity = record["fm"].get("maturity") or const.DEFAULT_CLAIM_MATURITY
    new_maturity = old_maturity
    if old_maturity == "provisional":
        new_maturity = "established"
        record["fm"]["maturity"] = new_maturity
        events.emit("CLAIM_MATURITY_CHANGED", stage="AUTHORIZE", workspace=slug,
                    payload={"id": record_id, "from": old_maturity, "to": new_maturity, "reason": "revalidation"})

    reval_note = f"Revalidated at {stamp_now}" + (f" (commit `{new_commit}`)" if new_commit else "")
    if new_maturity != old_maturity:
        reval_note += f" [maturity elevated: {old_maturity} -> {new_maturity}]"
    if note:
        reval_note += f": {note}"
    record["body"] = record["body"].rstrip() + f"\n\n> {reval_note}\n"

    path = store.update_record("claims", record, workspace=slug)
    index.reindex_doc("claims", slug, record["path"], record["fm"], record["body"])
    index.sync(kinds=("claims",))
    l0.write_all()
    events.emit("CLAIM_REVALIDATED", stage="AUTHORIZE", workspace=slug,
                payload={"id": record_id, "verified_commit": new_commit, "note": note, "maturity": new_maturity})
    return {"id": record_id, "workspace": slug, "status": "active",
            "verified_commit": new_commit, "path": str(path), "maturity": new_maturity}


def elevate(record_id: str, maturity: str = "canonical", workspace: str = "", note: str = "") -> dict:
    """Elevate a claim along the epistemic maturity ladder."""
    maturity = (maturity or "").strip().lower()
    if maturity not in const.CLAIM_MATURITIES:
        raise BrainError(f"invalid maturity {maturity!r}; choose from {', '.join(const.CLAIM_MATURITIES)}")
    found = store.find_record("claims", record_id) if not workspace else \
        (workspace, store.read_record("claims", record_id, workspace, strict=True))
    if not found:
        raise NotFound(f"claim {record_id} not found")
    slug, record = found
    old_maturity = record["fm"].get("maturity") or const.DEFAULT_CLAIM_MATURITY
    record["fm"]["maturity"] = maturity
    stamp_now = now()
    elevate_note = f"Maturity elevated: {old_maturity} -> {maturity} at {stamp_now}"
    if note:
        elevate_note += f": {note}"
    record["body"] = record["body"].rstrip() + f"\n\n> {elevate_note}\n"
    path = store.update_record("claims", record, workspace=slug)
    index.reindex_doc("claims", slug, record["path"], record["fm"], record["body"])
    index.sync(kinds=("claims",))
    l0.write_all()
    events.emit("CLAIM_MATURITY_CHANGED", stage="AUTHORIZE", workspace=slug,
                payload={"id": record_id, "from": old_maturity, "to": maturity, "note": note})
    return {"id": record_id, "workspace": slug, "maturity": maturity, "path": str(path)}


def invalidate_stale_claims(workspace: str = "", cwd=None) -> list:
    """Scan active claims and mark any whose dependency files changed in Git as needs_revalidation."""
    slugs = [workspace] if workspace else ws_mod.all_slugs()
    invalidated = []
    for record in store.all_records("claims", slugs):
        if record["fm"].get("status") != "active":
            continue
        v_commit = str(record["fm"].get("verified_commit") or "").strip()
        deps = record["fm"].get("depends_on") or []
        if not v_commit or not deps:
            continue
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.split(",") if d.strip()]

        ws_info = ws_mod.entry(record["workspace"])
        project_path = ws_info.get("path") if ws_info else ""
        if cwd:
            repo_path = cwd
        elif project_path and vcs.is_repo(project_path):
            repo_path = project_path
        elif vcs.is_repo(str(VAULT)):
            repo_path = str(VAULT)
        else:
            continue

        modified = vcs.changed_files(v_commit, cwd=repo_path)
        if not modified:
            continue

        # Check if any dependent file was touched
        hit = [f for f in deps if f in modified or any(f.endswith(m) or m.endswith(f) for m in modified)]
        if hit:
            record["fm"]["status"] = "needs_revalidation"
            stamp_now = now()
            record["body"] = record["body"].rstrip() + (
                f"\n\n> [{stamp_now}] Flagged NEEDS_REVALIDATION: file(s) modified in Git since `{v_commit}`: "
                + ", ".join(hit) + "\n"
            )
            store.update_record("claims", record, workspace=record["workspace"])
            index.reindex_doc("claims", record["workspace"], record["path"], record["fm"], record["body"])
            invalidated.append((record["id"], f"source files modified since {v_commit}: {', '.join(hit)}"))
            events.emit("CLAIM_INVALIDATED", stage="OBSERVE", workspace=record["workspace"],
                        payload={"id": record["id"], "reason": f"source files modified since {v_commit}: {', '.join(hit)}",
                                 "verified_commit": v_commit, "modified_files": hit})

    if invalidated:
        index.sync(kinds=("claims",))
        l0.write_all()
    return invalidated


def supersede(old_id: str, new_id: str) -> dict:
    old_found = store.find_record("claims", old_id)
    new_found = store.find_record("claims", new_id)
    if not old_found:
        raise NotFound(f"claim {old_id} not found")
    if not new_found:
        raise NotFound(f"claim {new_id} not found")
    old_slug, old = old_found
    new_slug, new = new_found
    stamp = now()
    old["fm"]["status"] = "superseded"
    old["fm"]["superseded_by"] = new_id
    old["body"] = old["body"].rstrip() + f"\n\nSuperseded by [[{new_id}]] on {stamp}.\n"
    new["fm"]["supersedes"] = old_id
    new["body"] = new["body"].rstrip() + f"\n\nSupersedes [[{old_id}]] on {stamp}.\n"
    store.update_record("claims", old, workspace=old_slug)
    store.update_record("claims", new, workspace=new_slug)
    events.emit("CLAIM_SUPERSEDED", stage="AUTHORIZE", workspace=new_slug,
                payload={"old_id": old_id, "new_id": new_id})
    return {"old": old_id, "new": new_id}


def dispute(record_id: str, reason: str = "", by: str = "") -> dict:
    found = store.find_record("claims", record_id)
    if not found:
        raise NotFound(f"claim {record_id} not found")
    slug, record = found
    record["fm"]["status"] = "disputed"
    record["fm"]["disputed_by"] = by or "unknown"
    record["fm"]["dispute_reason"] = reason.strip()
    record["body"] = record["body"].rstrip() + (
        f"\n\n> Disputed by {by or 'unknown'} on {now()}: {reason or '(no reason given)'}\n"
    )
    store.update_record("claims", record, workspace=slug)
    events.emit("CLAIM_DISPUTED", stage="AUTHORIZE", workspace=slug,
                payload={"id": record_id, "by": by or "unknown", "reason": reason.strip()})
    return {"id": record_id, "workspace": slug}


def promote(note_id: str, workspace: str = "", confidence: float = 0.9, tags="") -> dict:
    """Turn a context note into a claim, keeping the note's full text as evidence."""
    found = store.find_record("context", note_id)
    if not found:
        raise NotFound(f"context note {note_id} not found")
    slug, note = found
    body = (note.get("body") or "").strip()
    if not body:
        raise BrainError(f"context note {note_id} has no text to promote")
    summary = next((line.strip() for line in body.splitlines() if line.strip()), body)
    agent = note["fm"].get("agent", "unknown")
    result = add(
        text=summary,
        workspace=slug,
        confidence=confidence,
        source=f"context:{note_id} (by {agent})",
        tags=tags or note["fm"].get("tags", ""),
        evidence=body,
    )
    # Link the claim back to its origin so the chain is walkable in both directions.
    claim = store.read_record("claims", result["id"], slug)
    if claim:
        claim["fm"]["promoted_from"] = note_id
        store.update_record("claims", claim, workspace=slug)

    note["fm"]["promoted_to"] = result["id"]
    note["body"] = body + f"\n\n> Promoted to claim [[{result['id']}]] on {now()}\n"
    store.update_record("context", note, workspace=slug)
    return {**result, "promoted_from": note_id}


# ---- reading -------------------------------------------------------------


def _as_tags(tags) -> list:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw = [t.strip() for t in tags.split(",")]
    else:
        raw = [str(t).strip() for t in tags]
    seen, out = set(), []
    for tag in raw:
        lowered = tag.lower()
        if tag and lowered not in seen:
            seen.add(lowered)
            out.append(tag)
    return out


def _related_ids(tag_list, exclusive: str = "") -> list:
    if not tag_list:
        return []
    wanted = {t.lower() for t in tag_list}
    hits = []
    for row in index.search("claims", workspace=ws_mod.all_slugs()):
        if row["id"] == exclusive:
            continue
        row_tags = {t.strip().lower() for t in str(row.get("tags") or "").split(",") if t.strip()}
        if wanted & row_tags:
            hits.append(row["id"])
    return sorted(set(hits))[:5]


def recall(query: str = "", workspace: str = "", tag: str = "", status: str = "",
           maturity: str = "", include_withheld: bool = False, all_workspaces: bool = False,
           limit: int = 0):
    """Search claims. Scoped to the current workspace plus shared/global by default."""
    slug = workspace or ws_mod.default_workspace()
    scope = ws_mod.all_slugs() if all_workspaces else ws_mod.read_scope(slug)
    index.sync(kinds=("claims",))
    filters = {"status": status, "tags": tag}
    if maturity:
        filters["maturity"] = maturity
    rows = index.search(
        "claims", query=query, workspace=scope, limit=limit,
        filters=filters,
    )
    withheld_statuses = set(const.WITHHELD_STATUSES)
    shown, withheld = [], []
    for row in rows:
        entry = {
            "id": row["id"],
            "workspace": row.get("workspace", ""),
            "claim": row.get("claim", ""),
            "status": row.get("status") or "active",
            "confidence": row.get("confidence") or "",
            "maturity": row.get("maturity") or const.DEFAULT_CLAIM_MATURITY,
            "source": row.get("source", ""),
            "tags": row.get("tags", ""),
        }
        if entry["status"] in withheld_statuses and not include_withheld:
            withheld.append(entry)
        else:
            shown.append(entry)
    return shown, withheld


def get(record_id: str, workspace: str = ""):
    found = (workspace, store.read_record("claims", record_id, workspace)) if workspace \
        else store.find_record("claims", record_id)
    if not found or found[1] is None:
        raise NotFound(f"claim {record_id} not found")
    return found


def related(record_id: str, workspace: str = "") -> list:
    """Claims linked by shared tag, wikilink or supersede chain, either direction."""
    _, record = get(record_id, workspace)
    mine = {t.strip().lower() for t in str(record["fm"].get("tags") or "").split(",") if t.strip()}
    links = set(re.findall(r"\[\[([^\]|]+)", record.get("body") or ""))
    for key in ("supersedes", "superseded_by"):
        if record["fm"].get(key):
            links.add(str(record["fm"][key]))
    out = []
    for row in index.search("claims", workspace=ws_mod.all_slugs()):
        if row["id"] == record_id:
            continue
        reasons = []
        theirs = {t.strip().lower() for t in str(row.get("tags") or "").split(",") if t.strip()}
        if mine & theirs:
            reasons.append("shared-tag:" + ",".join(sorted(mine & theirs)))
        if row["id"] in links:
            reasons.append("linked")
        if record_id in re.findall(r"\[\[([^\]|]+)", str(row.get("body") or "")):
            reasons.append("backlink")
        if reasons:
            out.append({"id": row["id"], "workspace": row.get("workspace", ""),
                        "claim": row.get("claim", ""), "reasons": reasons})
    return sorted(out, key=lambda r: r["id"])


def chain_issues(record_id: str, workspace: str = "", seen=None) -> list:
    seen = seen or set()
    if record_id in seen:
        return [f"cycle detected at {record_id}"]
    seen.add(record_id)
    found = (workspace, store.read_record("claims", record_id, workspace)) if workspace \
        else store.find_record("claims", record_id)
    if not found or found[1] is None:
        return [f"dangling reference: {record_id} not found"]
    _, record = found
    issues = []
    for key in ("supersedes", "superseded_by"):
        target = str(record["fm"].get(key) or "").strip()
        if target and not store.find_record("claims", target):
            issues.append(f"{record_id}: {key} -> {target} is dangling (target missing)")
    if record["fm"].get("promoted_from"):
        if not store.find_record("context", str(record["fm"]["promoted_from"])):
            issues.append(f"{record_id}: promoted_from -> {record['fm']['promoted_from']} missing")
    return issues


def clear_dangling(record_id: str, workspace: str = "") -> list:
    """Remove links whose target no longer exists, recording what was removed.

    A dangling link is a permanent red on `brain verify`, which trains people to
    ignore it. Clearing is explicit (never automatic) and leaves a note in the body so
    the loss of the reference is itself part of the record.
    """
    slug, record = get(record_id, workspace)
    fixed = []
    for key in ("supersedes", "superseded_by", "promoted_from"):
        target = str(record["fm"].get(key) or "").strip()
        if not target:
            continue
        kind = "context" if key == "promoted_from" else "claims"
        if store.find_record(kind, target):
            continue
        record["fm"][key] = ""
        fixed.append(f"{key} -> {target}")
    if fixed:
        record["body"] = record["body"].rstrip() + (
            f"\n\n> {now()} dangling reference(s) cleared by `brain verify --fix`: "
            + ", ".join(fixed) + "\n"
        )
        store.update_record("claims", record, workspace=slug)
    return fixed


def verify(record_id: str = "", deep: bool = False) -> list:
    """Hard problems only: schema violations, dangling chains, failed round-trips.

    Unreviewed claims are reported separately by `unreviewed()` — they are a soft
    signal, not a defect, and folding them in here would make `brain verify`
    permanently red and therefore ignored.
    """
    if record_id:
        return chain_issues(record_id)
    issues = store.scan_problems(kinds=("claims",)) if deep else []
    for record in store.all_records("claims"):
        issues += chain_issues(record["id"], workspace=record["workspace"])
    return issues


def unreviewed(workspace: str = "", all_workspaces: bool = True) -> list:
    """Active claims nobody has ever run `brain review` on."""
    slugs = None if all_workspaces else (ws_mod.read_scope(workspace or ws_mod.default_workspace()))
    out = []
    for record in store.all_records("claims", slugs):
        if record["fm"].get("status") != "active":
            continue
        if parse_ts(record["fm"].get("reviewed_at")) is None:
            created = parse_ts(record["fm"].get("created"))
            age = (parse_ts(now()) - created).days if created else None
            out.append({"id": record["id"], "workspace": record["workspace"],
                        "age_days": age, "claim": claim_text(record)})
    return sorted(out, key=lambda r: (r["age_days"] is None, -(r["age_days"] or 0)))


def reclassify(workspace: str = const.GLOBAL_WORKSPACE, dry_run: bool = False,
               all_workspaces: bool = False, limit: int = 0) -> tuple:
    """Move records into the workspace their content actually indicates.

    Legacy claims carried no project field, so the migration filed anything it could not
    place into shared `global`. That is honest but noisy: every workspace's brief then
    shows research that belongs to one project. This re-scores each record against the
    registered aliases and keywords and relocates the confident matches.
    """
    slugs = ws_mod.all_slugs() if all_workspaces else [workspace]
    moved, kept = [], 0
    for kind in ("claims", "context", "tasks", "specs", "sessions"):
        for record in store.all_records(kind, slugs):
            # Score the record's own identity fields, not its body. Long environment
            # notes mention every project in passing, and body text made them look
            # project-specific — the reason the previous heuristic filed everything
            # into one bucket.
            text = " ".join(str(v) for v in (record["fm"].get("tags"),
                                             record["fm"].get("source"),
                                             record["fm"].get("claim"),
                                             record["fm"].get("title"),
                                             record["fm"].get("project"),
                                             record["fm"].get("spec_id")))
            scored = sorted(
                ((ws_mod.score_detail(text, slug), slug) for slug in ws_mod.all_slugs()
                 if slug != const.GLOBAL_WORKSPACE),
                key=lambda pair: (3 * pair[0][0] + pair[0][1]),
                reverse=True,
            )
            if not scored:
                kept += 1
                continue
            (names_hit, keywords_hit), best = scored[0]
            best_score = 3 * names_hit + keywords_hit
            other = scored[1][0] if len(scored) > 1 else (0, 0)
            beats_others = best_score > 3 * other[0] + other[1]
            # Require an explicit project name, or several independent topical terms.
            # Most shared notes describe the machine and the agent setup, which is
            # genuinely cross-project; forcing those into a project would be worse.
            confident = names_hit >= 1 or keywords_hit >= 2
            if best == record["workspace"] or not beats_others or not confident:
                kept += 1
                continue
            moved.append({"kind": kind, "id": record["id"], "from": record["workspace"],
                          "to": best, "score": best_score,
                          "names": names_hit, "keywords": keywords_hit,
                          "claim": (claim_text(record) or str(record["fm"].get("title") or ""))[:70]})
            if not dry_run:
                store.move_record(kind, record, best)
            if limit and len(moved) >= limit:
                break
    return moved, kept


def stats() -> dict:
    counts = {status: 0 for status in const.STATUSES}
    total = 0
    by_workspace = {}
    for record in store.all_records("claims"):
        total += 1
        status = str(record["fm"].get("status") or "active")
        counts[status] = counts.get(status, 0) + 1
        by_workspace[record["workspace"]] = by_workspace.get(record["workspace"], 0) + 1
    return {"total": total, "by_status": counts, "by_workspace": by_workspace,
            "global": by_workspace.get(const.GLOBAL_WORKSPACE, 0)}
