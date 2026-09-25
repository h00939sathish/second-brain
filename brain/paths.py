# -*- coding: utf-8 -*-
"""Vault resolution, atomic writes and a cross-platform advisory lock."""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import const

# ---- vault ---------------------------------------------------------------

USER_CONFIG = Path.home() / ".config" / "second-brain" / "vault"


def vault_path() -> Path:
    """Resolve the vault.

    Order: $SECOND_BRAIN_VAULT -> ~/.config/second-brain/vault -> the directory
    containing this package. Never raises; returns a Path even if it is missing
    so callers can produce their own error message.
    """
    env = os.environ.get("SECOND_BRAIN_VAULT")
    if env:
        return Path(env).expanduser().resolve()
    try:
        if USER_CONFIG.exists():
            raw = USER_CONFIG.read_text(encoding="utf-8").strip()
            if raw:
                return Path(raw).expanduser().resolve()
    except OSError:
        pass
    return Path(__file__).resolve().parent.parent


VAULT = vault_path()

META_DIR = const.META_DIR
WORKSPACES_DIR = const.WORKSPACES_DIR
L0_NAME = const.L0_NAME
DB_NAME = const.DB_NAME


def meta_path() -> Path:
    return VAULT / META_DIR


def config_path() -> Path:
    return meta_path() / const.CONFIG_NAME


def workspaces_path() -> Path:
    return meta_path() / const.WORKSPACES_NAME


def l0_path() -> Path:
    return meta_path() / const.L0_NAME


def db_path() -> Path:
    return meta_path() / const.DB_NAME


def heartbeat_path() -> Path:
    return meta_path() / const.HEARTBEAT_NAME


def workspaces_root() -> Path:
    return VAULT / WORKSPACES_DIR


def logs_dir(workspace: str = "") -> Path:
    """Dispatch logs live per workspace so two projects never share a log file."""
    from . import workspaces as ws_mod  # local import avoids an import cycle
    ws = workspace or ws_mod.default_workspace()
    return workspaces_root() / ws / "logs"


def is_initialised() -> bool:
    return meta_path().is_dir()


# ---- time ----------------------------------------------------------------


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(ts_str):
    """Parse an ISO second-precision timestamp. Returns None when unusable."""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(str(ts_str).strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def time_ago(ts_str) -> str:
    ts = parse_ts(ts_str)
    if ts is None:
        return "?"
    seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    if seconds < 0:
        return "just now"
    if seconds >= 86400:
        return f"{int(seconds // 86400)}d ago"
    if seconds >= 3600:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 60)}m ago"


def stamp(minutes: int = 0, days: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes, days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- writing -------------------------------------------------------------


def atomic_write(path: Path, content: str) -> None:
    """Write via tmp + rename so a reader never sees a half-written record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_text(path: Path) -> str:
    """Read with universal newlines so CRLF records written on Windows still parse."""
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, data) -> None:
    atomic_write(path, json.dumps(data, indent=2, sort_keys=False) + "\n")


def read_json(path: Path, default=None):
    try:
        return json.loads(read_text(path))
    except (OSError, ValueError):
        return default


# ---- locking -------------------------------------------------------------


class FileLock:
    """Advisory exclusive lock, non-blocking with a bounded wait.

    POSIX uses fcntl.flock; Windows uses msvcrt.locking. If neither is available
    the lock degrades to a no-op rather than breaking single-user workflows.
    """

    def __init__(self, path: Path, timeout: float = 15.0):
        self.path = Path(path)
        self.timeout = timeout
        self._fh = None
        self._locked = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not self.path.exists() or self.path.stat().st_size == 0:
                with open(self.path, "ab") as fh:
                    fh.write(b"0")
            self._fh = open(self.path, "r+b")
        except OSError:
            self._fh = None
            return self

        if os.name == "nt":
            import msvcrt
        else:
            try:
                import fcntl
            except ImportError:
                fcntl = None
        deadline = time.time() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._locked = True
                break
            except OSError:
                if time.time() > deadline:
                    self._close()
                    raise TimeoutError(
                        f"could not acquire {self.path} within {self.timeout}s "
                        "(another brain process is holding it)"
                    )
                time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        if self._locked and self._fh is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except (OSError, ImportError):
                pass
            finally:
                self._locked = False
        self._close()
        return False

    def _close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def lock(timeout: float = 15.0) -> FileLock:
    return FileLock(VAULT / ".lock", timeout=timeout)


def bypass_enabled(spend: bool = True, seat: str = "", action: str = "",
                   workspace: str = "") -> bool:
    """Whether the boundary may be stepped over *right now*.

    A late import keeps this reachable from everywhere without dragging the attestation
    and event machinery into `paths`, which half the vault imports.
    """
    from . import grants
    ok, _ = grants.bypass(seat=seat, action=action, workspace=workspace, spend=spend)
    return ok


def is_windows() -> bool:
    return os.name == "nt"


def stdout_utf8() -> None:
    """Keep emoji/box output from crashing on a cp1252 console."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
