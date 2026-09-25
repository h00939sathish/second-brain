# -*- coding: utf-8 -*-
"""Incremental SQLite FTS5 index that is actually used for reads.

Previously every mutation dropped and rebuilt all four FTS tables, while every read
parsed every markdown file on disk and used the index only for an id->rank map. The
index was pure overhead.

Now:
  * a write reindexes exactly one document
  * a read does a cheap stat-walk (`sync`) and reparses only files that changed,
    which also picks up hand edits made outside the engine
  * a search returns rows straight from SQL, so a recall no longer touches disk
"""

import hashlib
import re
import sqlite3
from pathlib import Path

from . import workspaces as ws_mod
from .paths import db_path

KINDS = ("claims", "specs", "tasks", "context", "sessions")

# Columns exposed by each index table.
SCHEMA = {
    "claims": ("id", "claim", "tags", "source", "status", "confidence", "maturity", "workspace",
               "path", "body"),
    "specs": ("id", "title", "project", "phases", "workspace", "path", "body"),
    "tasks": ("id", "title", "project", "spec_id", "agent", "status", "workspace",
              "path", "body"),
    "context": ("id", "agent", "project", "tags", "created", "workspace", "path", "body"),
    "sessions": ("id", "agent", "project", "task", "files", "status", "workspace",
                 "path", "body"),
}
# Columns FTS should not tokenise (they are still stored, and still selectable).
UNINDEXED = {"id", "status", "confidence", "maturity", "workspace", "path", "created", "spec_id",
             "project", "agent", "phases", "files"}

_AVAILABLE = None


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def available() -> bool:
    """True when this sqlite build ships FTS5. Otherwise we degrade to LIKE scans."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            probe = sqlite3.connect(":memory:")
            probe.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            probe.close()
            _AVAILABLE = True
        except sqlite3.OperationalError:
            _AVAILABLE = False
    return _AVAILABLE


def _table(kind: str) -> str:
    return f"{kind}_fts" if available() else f"{kind}_idx"


SCHEMA_VERSION = 3


def init() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
        row = cur.execute("SELECT value FROM index_meta WHERE key = 'schema_version'").fetchone()
        if row is None or str(row[0]) != str(SCHEMA_VERSION):
            # A vault indexed by an older build has incompatible columns (the previous
            # schema had no `workspace`), and CREATE ... IF NOT EXISTS would silently
            # keep it. Rebuild instead.
            for kind in SCHEMA:
                cur.execute(f"DROP TABLE IF EXISTS {kind}_fts")
                cur.execute(f"DROP TABLE IF EXISTS {kind}_idx")
            cur.execute("DROP TABLE IF EXISTS doc_index")
            cur.execute("INSERT OR REPLACE INTO index_meta (key, value) VALUES ('schema_version', ?)",
                        (str(SCHEMA_VERSION),))
        for kind, cols in SCHEMA.items():
            if available():
                col_defs = ", ".join(f"{c} UNINDEXED" if c in UNINDEXED else c for c in cols)
                cur.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {kind}_fts USING fts5({col_defs});")
            else:
                col_defs = ", ".join(f"{c} TEXT" for c in cols)
                cur.execute(f"CREATE TABLE IF NOT EXISTS {kind}_idx ({col_defs});")
                cur.execute(f"CREATE INDEX IF NOT EXISTS {kind}_idx_ws ON {kind}_idx(workspace);")
        # Freshness bookkeeping: a stat-only comparison decides what to reparse.
        cur.execute(
            "CREATE TABLE IF NOT EXISTS doc_index ("
            "  kind TEXT NOT NULL, id TEXT NOT NULL, workspace TEXT NOT NULL,"
            "  path TEXT NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL,"
            "  hash TEXT NOT NULL, PRIMARY KEY (kind, id, workspace));"
        )
        conn.commit()
    finally:
        conn.close()


# ---- writing -------------------------------------------------------------


def _values(kind: str, workspace: str, path: Path, fm: dict, body: str) -> dict:
    cols = SCHEMA[kind]
    values = {c: "" for c in cols}
    values.update({k: ("" if v is None else str(v)) for k, v in fm.items() if k in cols})
    values["id"] = str(fm.get("id") or Path(path).stem)
    values["workspace"] = workspace
    values["path"] = str(path)
    values["body"] = body or ""
    return values


def remove(kind: str, record_id: str, workspace: str) -> None:
    conn = _connect()
    try:
        conn.execute(f"DELETE FROM {_table(kind)} WHERE id = ? AND workspace = ?",
                     (record_id, workspace))
        conn.execute("DELETE FROM doc_index WHERE kind = ? AND id = ? AND workspace = ?",
                     (kind, record_id, workspace))
        conn.commit()
    finally:
        conn.close()


def reindex_doc(kind: str, workspace: str, path: Path, fm: dict, body: str) -> None:
    """Reindex a single document. Every write calls this instead of a full rebuild."""
    init()
    path = Path(path)
    record_id = str(fm.get("id") or path.stem)
    values = _values(kind, workspace, path, fm, body)
    digest = hashlib.sha1(
        repr(sorted((k, str(v)) for k, v in values.items())).encode("utf-8")
    ).hexdigest()
    try:
        stat = path.stat()
        mtime, size = stat.st_mtime, stat.st_size
    except OSError:
        mtime, size = 0.0, 0

    cols = SCHEMA[kind]
    conn = _connect()
    try:
        conn.execute(f"DELETE FROM {_table(kind)} WHERE id = ? AND workspace = ?",
                     (record_id, workspace))
        conn.execute(
            f"INSERT INTO {_table(kind)} ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})",
            tuple(values[c] for c in cols),
        )
        conn.execute(
            "INSERT OR REPLACE INTO doc_index (kind, id, workspace, path, mtime, size, hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, record_id, workspace, str(path), mtime, size, digest),
        )
        conn.commit()
    finally:
        conn.close()


def sync(kinds=KINDS, workspace: str = "", verbose: bool = False) -> int:
    """Stat-walk the vault and reparse only documents whose file changed.

    Reads call this so the index stays honest even when a human or an agent edits
    markdown directly. Returns the number of documents reparsed.
    """
    from . import store  # local import avoids a cycle (store imports index)

    init()
    conn = _connect()
    try:
        rows = conn.execute("SELECT kind, id, workspace, mtime, size FROM doc_index").fetchall()
    finally:
        conn.close()
    known = {(kind, doc, ws): (mtime, size) for kind, doc, ws, mtime, size in rows}

    reparsed = 0
    slugs = [workspace] if workspace else ws_mod.all_slugs()
    for slug in slugs:
        for kind in kinds:
            directory = ws_mod.subdir(slug, kind)
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if known.get((kind, path.stem, slug)) == (stat.st_mtime, stat.st_size):
                    continue
                record = store.read_record(kind, path.stem, workspace=slug)
                if record is None:
                    continue
                reindex_doc(kind, slug, path, record["fm"], record["body"])
                reparsed += 1
                if verbose:
                    print(f"  indexed {kind}/{slug}/{path.stem}")
    return reparsed


def reindex_all(verbose: bool = False) -> int:
    """Force a full rebuild. Only `init`, `migrate` and `reindex` should need this."""
    init()
    conn = _connect()
    try:
        for kind in KINDS:
            conn.execute(f"DELETE FROM {_table(kind)}")
        conn.execute("DELETE FROM doc_index")
        conn.commit()
    finally:
        conn.close()
    return sync(verbose=verbose)


# ---- querying ------------------------------------------------------------


def fts_query(text: str) -> str:
    """Turn a user string into a safe FTS5 MATCH expression (prefix per token)."""
    tokens = [t for t in re.split(r"\s+", (text or "").strip()) if t]
    parts = []
    for token in tokens:
        operator = token.upper()
        if operator in ("AND", "OR", "NOT"):
            parts.append(operator)
            continue
        cleaned = token.replace('"', "").strip()
        if cleaned:
            parts.append(f'"{cleaned}"*')
    return " ".join(parts)


def search(kind: str, query: str = "", workspace=(), limit: int = 0,
           filters=None, order: str = "rank"):
    """Return matching rows straight from the index, best match first.

    `workspace` is an iterable of slugs; `filters` is a column->value mapping ANDed
    onto the query. Returns [] on any SQL failure so the caller can fall back to disk.
    """
    init()
    cols = SCHEMA[kind]
    table = _table(kind)
    term = (query or "").strip()
    clauses, args = [], []

    if term:
        if available():
            clauses.append(f"{table} MATCH ?")
            args.append(fts_query(term))
        else:
            like_cols = [c for c in cols if c != "id"]
            clauses.append("(" + " OR ".join(f"{c} LIKE ?" for c in like_cols) + ")")
            args.extend([f"%{term}%"] * len(like_cols))

    slugs = [w for w in (workspace or []) if w]
    if slugs:
        clauses.append("workspace IN (" + ", ".join("?" for _ in slugs) + ")")
        args.extend(slugs)

    for column, value in (filters or {}).items():
        if column not in cols or value in (None, ""):
            continue
        clauses.append(f"{column} LIKE ?")
        args.append(f"%{value}%")

    sql = f"SELECT {', '.join(cols)} FROM {table}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if term and available() and order == "rank":
        sql += " ORDER BY rank"
    elif order == "recent":
        sql += " ORDER BY rowid DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    conn = _connect()
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [dict(zip(cols, row)) for row in rows]
