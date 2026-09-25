# -*- coding: utf-8 -*-
"""Machine evidence: the runtime, not the agent, decides what happened (INV-002).

Three properties this module has to keep, and previously did not:
  * an agent cannot declare an exit code (`record-evidence` is gone, receipts come from
    a process this code started, or from the privileged witness);
  * an agent cannot sign a receipt once trust is installed, because the key is
    root-owned and unreadable at the agents' uid;
  * an agent cannot edit a transcript after the fact, because the hash is recomputed
    at verification time and compared against the signed one.
"""

import hashlib
import json
import os
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from . import attest, board, const, events, store, vcs, workspaces as ws_mod
from .errors import BrainError
from .paths import VAULT, atomic_write, now


def receipts_dir(workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    directory = ws_mod.subdir(slug, "receipts")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def witness_available() -> bool:
    return attest.installed() and Path(const.WITNESS_BINARY).is_file()


def _claim_session(session_id: str, slug: str, task_id: str = "") -> None:
    """A receipt speaks for the session that did the work, so only that seat may file it.

    `session_id` used to be a free-text field: one seat could attribute its own evidence to
    another seat's session and have it read back as that seat's finished work, or attach a
    passing run from an unrelated card to the one it wanted closed.
    """
    from . import coordination
    found = coordination.get(session_id, slug)
    session = found[1] if isinstance(found, tuple) else found
    if not session:
        raise BrainError(f"receipt refused: no session {session_id} in workspace "
                         f"'{slug}' to attach evidence to")
    fm = session.get("fm") or {}
    holder = board.resolve_agent(fm.get("agent"))
    asker = board.seat()
    if asker and holder and asker != holder:
        events.emit("EVIDENCE_ATTRIBUTION_REFUSED", stage="VERIFY", workspace=slug,
                    actor=f"seat:{asker}",
                    payload={"session": session_id, "holder": holder})
        raise BrainError(f"receipt refused: session {session_id} belongs to {holder}, not "
                         f"{asker}. File your evidence under a session you hold.")
    worked_on = str(fm.get("task_id") or "")
    if task_id and worked_on and worked_on != task_id:
        events.emit("EVIDENCE_ATTRIBUTION_REFUSED", stage="VERIFY", workspace=slug,
                    actor=f"seat:{asker or holder or '?'}",
                    payload={"session": session_id, "task": worked_on})
        raise BrainError(f"receipt refused: session {session_id} is working {worked_on}, "
                         f"not {task_id}. A run elsewhere is not evidence here.")


def record_receipt(task_id: str, command: str, exit_code: int, stdout: str = "",
                   stderr: str = "", duration_ms: int = 0, workspace: str = "",
                   session_id: str = "", cwd: str = "", transcript_log: str = "") -> dict:
    """Seal one execution record. Raises rather than writing unverifiable evidence."""
    slug = workspace or ws_mod.default_workspace()
    if session_id:
        _claim_session(session_id, slug, task_id=task_id)
    ws_info = ws_mod.entry(slug)
    repo_dir = cwd or (ws_info.get("path") if ws_info else None) or str(VAULT)

    ts = now()
    now_f = time.time()
    date_compact = ts[:10].replace("-", "")
    receipt_id = f"rcpt_{date_compact}_{int(now_f * 1000)}_{uuid.uuid4().hex[:4]}"

    transcript_sha256 = ""
    transcript_excerpt = ""
    if transcript_log and Path(transcript_log).exists():
        log_bytes = Path(transcript_log).read_bytes()
        transcript_sha256 = hashlib.sha256(log_bytes).hexdigest()
        transcript_excerpt = "\n".join(
            log_bytes.decode("utf-8", errors="replace").splitlines()[-20:])

    snippet = (stdout or "")
    if stderr:
        snippet = (snippet + "\n[stderr]\n" + stderr).strip()

    git_head = vcs.head_commit(repo_dir) if vcs.is_repo(repo_dir) else ""

    receipt = {
        "receipt_id": receipt_id,
        "task_id": task_id,
        "workspace": slug,
        "session_id": session_id or "",
        "command": command or "",
        "exit_code": int(exit_code),
        "stdout_hash": _digest(stdout),
        "stderr_hash": _digest(stderr),
        "transcript_path": str(transcript_log or ""),
        "transcript_sha256": transcript_sha256,
        "transcript_excerpt": transcript_excerpt,
        "output_snippet": snippet[:500],
        "duration_ms": int(duration_ms),
        "timestamp": ts,
        "recorded_at": now_f,
        "cwd": repo_dir,
        "git_head": git_head,
        "witnessed_by": "in-process" if not witness_available() else "brain-witness",
        "verified": int(exit_code) == 0,
    }

    try:
        signed = attest.seal_to_file(receipts_dir(slug) / f"{receipt_id}.json", receipt)
    except PermissionError as exc:
        raise exc

    signed["_attestation"] = attestation_of(signed)
    signed["_trust_mode"] = (signed.get(attest.ATTEST_FIELD) or {}).get("trust_mode", "unknown")

    events.emit("EVIDENCE_RECORDED", stage="OBSERVE", workspace=slug, task_id=task_id,
                payload={k: v for k, v in signed.items() if k != "attestation"})
    return signed


def attestation_of(receipt: dict) -> str:
    """VERIFIED / FORGED / UNSIGNED / NO_TRUST_ROOT for one receipt."""
    return attest.verify(receipt or {})


def load_receipt(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["_attestation"] = attestation_of(data)
    data["_trust_mode"] = (data.get(attest.ATTEST_FIELD) or {}).get("trust_mode", "unknown")
    return data


def get_receipts(task_id: str = "", workspace: str = "", limit: int = 50) -> list:
    """Retrieve execution receipts, newest first, each tagged with its attestation state.

    Tampered records are returned and labelled, never silently dropped: an agent deleting
    or editing evidence has to leave a trace the reviewer can see.
    """
    slug = workspace or ws_mod.default_workspace()
    rdir = receipts_dir(slug)
    receipts = []
    if not rdir.is_dir():
        return []

    for path in sorted(rdir.glob("*.json")):
        data = load_receipt(path)
        if not data:
            continue
        if task_id and str(data.get("task_id") or "") != task_id:
            continue
        receipts.append(data)

    receipts.sort(key=lambda r: (str(r.get("timestamp") or ""),
                                 float(r.get("recorded_at") or 0.0),
                                 str(r.get("receipt_id") or "")), reverse=True)
    return receipts[:limit] if limit > 0 else receipts


def _normalise(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("./").strip("/")


def _exit_code(receipt: dict) -> int:
    """The recorded exit status. `or 1` on a real 0 would read success as failure."""
    raw = (receipt or {}).get("exit_code")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def transcript_intact(receipt: dict) -> tuple:
    """Recompute the transcript hash at verification time and compare to the signed one."""
    claimed = str(receipt.get("transcript_sha256") or "")
    if not claimed:
        return True, "no transcript bound to this receipt"
    path = str(receipt.get("transcript_path") or "")
    if not path or not Path(path).is_file():
        return False, f"transcript {path or '(unset)'} is gone but the receipt claims a hash"
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual != claimed:
        return False, ("transcript modified after the receipt was sealed "
                       f"(signed {claimed[:12]}…, now {actual[:12]}…)")
    return True, "ok"


def run_test(task_id: str, command: str, cwd: str = None, workspace: str = "",
             session_id: str = "", timeout: int = 120) -> dict:
    """Execute a test command and record a receipt for what actually happened.

    Once trust is installed the execution and the sealing happen in the privileged
    witness, because a process running as the agent cannot be the authority on its own
    exit code. Before that, this is in-process and every receipt says so.
    """
    slug = workspace or ws_mod.default_workspace()
    ws_info = ws_mod.entry(slug)
    run_cwd = cwd or (ws_info.get("path") if ws_info else None) or str(VAULT)

    if witness_available():
        return _run_witnessed(task_id, command, run_cwd, slug, session_id, timeout)

    argv = shlex.split(command) if command else []
    if not argv:
        raise ValueError("a test command is required")
    start_time = time.monotonic()
    log_dir = VAULT / const.WORKSPACES_DIR / slug / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    transcript = log_dir / f"{task_id or 'adhoc'}.{int(time.time())}.transcript.log"
    try:
        with open(transcript, "wb") as sink:
            proc = subprocess.run(argv, stdout=sink, stderr=subprocess.STDOUT,
                                  cwd=run_cwd, timeout=timeout, start_new_session=True)
        exit_code, duration = int(proc.returncode), int((time.monotonic() - start_time) * 1000)
        text = transcript.read_text(encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        exit_code, duration = 124, int((time.monotonic() - start_time) * 1000)
        text = f"command timed out after {timeout} seconds"
        transcript.write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        exit_code, duration, text = 127, 0, f"could not run: {exc}"
        transcript.write_text(text, encoding="utf-8")
    return record_receipt(task_id=task_id, command=command, exit_code=exit_code,
                          stdout=text, duration_ms=duration, workspace=slug,
                          session_id=session_id, cwd=run_cwd,
                          transcript_log=str(transcript))


def _run_witnessed(task_id: str, command: str, run_cwd: str, slug: str,
                   session_id: str, timeout: int) -> dict:
    argv = shlex.split(command) if command else []
    if not argv:
        raise ValueError("a test command is required")
    call = ["sudo", "-n", const.WITNESS_BINARY, "exec", "--task", task_id,
            "--workspace", slug, "--cwd", run_cwd, "--timeout", str(int(timeout)),
            "--vault", str(VAULT)]
    if session_id:
        call += ["--session", session_id]
    call += ["--"] + argv
    res = subprocess.run(call, capture_output=True, text=True, timeout=timeout + 60)
    if res.returncode not in (0, 1):
        detail = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(f"witness refused: {detail or f'exit {res.returncode}'}")
    try:
        sealed = json.loads(res.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("witness returned no receipt")
    sealed["_attestation"] = attestation_of(sealed)
    sealed["_trust_mode"] = (sealed.get(attest.ATTEST_FIELD) or {}).get("trust_mode", "?")
    return sealed


def check_working_tree(workspace: str = "", leased_files: list = None, cwd: str = None) -> tuple:
    """Verify no *code* changed outside the session lease.

    Only the code zone is judged here. Paths under workspaces/ are excluded on purpose:
    the brain writes cards, sessions, events and receipts there constantly, so a git
    comparison would drown in its own bookkeeping. Those zones are policed by something
    stronger instead — receipts by attestation plus transcript recomputation, topology by
    its pinned digest, and state writes by the guard.
    """
    slug = workspace or ws_mod.default_workspace()
    ws_info = ws_mod.entry(slug)
    project_path = ws_info.get("path") if ws_info else ""
    root = str(Path(project_path or VAULT).resolve())
    if cwd:
        # A caller-chosen directory is a caller-chosen answer: pointed at any clean repo,
        # this check would report "nothing changed outside the lease". The workspace
        # registration decides what the tree even is.
        resolved = str(Path(cwd).resolve())
        if resolved != root and not resolved.startswith(root + os.sep):
            return False, [f"cwd {cwd} is outside workspace '{slug}' (root {root})"]
    # cwd never picks the tree, not even a tree inside the workspace: judging a
    # subdirectory would report "not a repository" and call the whole workspace clean.
    repo_dir = root if vcs.is_repo(root) else ""

    if not repo_dir or not vcs.is_repo(repo_dir):
        return True, []

    head = vcs.head_commit(repo_dir)
    changed = vcs.changed_files(head, cwd=repo_dir)
    if not changed:
        return True, []

    leased = {_normalise(f) for f in (leased_files or [])}
    outside = []
    for f in changed:
        path = _normalise(f)
        if const.zone_for_path(path) != const.ZONE_CODE:
            continue
        if path in leased or any(path == l or path.startswith(l + "/") for l in leased):
            continue
        outside.append(f)

    if outside:
        return False, outside
    return True, []


def verify_task(task_id: str, workspace: str = "", test_status_claimed: str = "",
                leased_files: list = None, target_agent: str = "", cwd: str = None) -> tuple:
    """Validate task evidence against attested execution records and tree integrity.

    Returns (ok, detail). A hand-written assertion that a reviewer waved the card through
    is not evidence and no longer clears this gate; only an attested exit code 0 does.
    """
    slug = workspace or ws_mod.default_workspace()

    clean_ok, outside = check_working_tree(slug, leased_files=leased_files, cwd=cwd)
    if not clean_ok:
        return False, f"working tree contains changes outside session lease: {', '.join(outside)}"

    receipts = get_receipts(task_id, slug)
    tampered = [r for r in receipts if r.get("_attestation") != attest.VERIFIED]
    for bad in tampered:
        events.emit("EVIDENCE_REJECTED", stage="AUTHORIZE", workspace=slug, task_id=task_id,
                    payload={"receipt_id": bad.get("receipt_id"),
                             "reason": bad.get("_attestation")})
    usable = [r for r in receipts if r.get("_attestation") == attest.VERIFIED]

    if tampered and not usable:
        kinds = ", ".join(sorted({str(r.get("_attestation")) for r in tampered}))
        return False, (f"{len(tampered)} receipt(s) for {task_id} failed attestation "
                       f"({kinds}); no verified execution evidence exists")

    if usable:
        latest = usable[0]
        intact, why = transcript_intact(latest)
        if not intact:
            return False, why
        code = _exit_code(latest)
        if code != 0:
            failed = [r for r in usable if _exit_code(r) != 0]
            return False, (f"execution receipt {latest['receipt_id']} failed with exit code "
                           f"{code} ({len(failed)} failing receipt(s) on record for this task)")
        suffix = "" if len(usable) == 1 else f"; {len(usable) - 1} older attested receipt(s)"
        if tampered:
            suffix += f"; WARNING {len(tampered)} tampered receipt(s) present"
        badge = "" if latest.get("_trust_mode") == "installed" else \
            f" [{latest.get('_trust_mode', '?')} trust]"
        return True, f"verified execution receipt {latest['receipt_id']} (exit code 0{badge}){suffix}"

    if test_status_claimed:
        return False, (f"fabricated test status {test_status_claimed!r} without OS execution "
                       f"receipt (no attested record on file)")
    return False, f"no execution receipt recorded for task {task_id}"
