#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain-witness — the privileged execution witness for the Second Brain.

INSTALLED ROOT-OWNED AT /usr/local/bin/brain-witness AND NEVER IMPORTED FROM THE VAULT.
That is the whole point: an agent owns every file under the vault, so anything this
process imports must live outside it, or "run the witness" becomes local root.

It does exactly four things, all of which an agent at uid 1000 cannot do for itself:
  1. run an allow-listed test command as the *agent's own* uid and observe the real exit code
  2. hash the transcript it captured itself
  3. sign the result with a key the agent cannot read, into a directory the agent cannot write
  4. consume a bypass grant, so single-use survives a root-owned grants directory

It is invoked as:  sudo -n brain-witness exec --task ID --session ID --cwd DIR -- argv...
                  sudo -n brain-witness spend-grant GRANT_ID
                  sudo -n brain-witness pin-topology --workspace SLUG
                  sudo -n brain-witness grant-bypass --reason TEXT --minutes N
The first two are NOPASSWD — an agent can make real evidence and can only *close* its own
way out. The last two require a password, so only a human can change policy or authorise
a bypass.
"""

import base64
import hashlib
import json
import os
import pwd
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

TRUST_DIR = "/etc/second-brain"
_VAULT = ""
KEY_FILE = os.path.join(TRUST_DIR, "attest.key")
FPR_FILE = os.path.join(TRUST_DIR, "attest.fpr")
VAULTS_FILE = os.path.join(TRUST_DIR, "vaults")
ALLOWED_FILE = os.path.join(TRUST_DIR, "allowed-commands")
# The child gets this PATH and nothing else, and `permitted()` resolves allow-listed names
# against it, so a poisoned $PATH in the caller's environment can neither hide nor fake a
# test runner.
FIXED_PATH = "/usr/local/sbin:/usr/local/bin:/usr/bin"
# Commands that exit 0 without exercising anything. On the allow-list they would be a
# passwordless route to a root-sealed "test passed" for a test that never ran.
NO_EVIDENCE = ("--help", "-h", "--version", "-V", "--collect-only", "--dry-run", "-n")
# The evidence zones. A sealed file only means something if the directory holding it is
# root's too: otherwise the agent unlinks it, or moves a spent grant back into the set
# `grants/` reads as live.
ROOT_OWNED_DIRS = ("receipts", "grants", "used")
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
DEFAULT_TIMEOUT = 600
MAX_TIMEOUT = 3600


def die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"brain-witness: {msg}\n")
    raise SystemExit(code)


def require_root() -> None:
    if os.geteuid() != 0:
        die("must run as root (sudo -n brain-witness ...); the key and the "
            "receipt directory are only reachable from here")


def vault_root(explicit: str = "") -> str:
    """Refuse to write evidence anywhere the operator has not allow-listed.

    `explicit` (and the module default filled in by `main`) exists because sudo resets
    the environment: a `--vault` flag survives where $SECOND_BRAIN_VAULT would not.
    Either way the allow-list decides, so a flag cannot point the witness at a new vault.
    """
    try:
        allowed = [l.strip() for l in open(VAULTS_FILE) if l.strip()
                   and not l.strip().startswith("#")]
    except OSError:
        die(f"no vault allow-list at {VAULTS_FILE}; refusing to write evidence")
    env = (explicit or _VAULT or os.environ.get("SECOND_BRAIN_VAULT", "")).strip()
    if not env:
        die("pass --vault or set SECOND_BRAIN_VAULT: must name an allow-listed vault")
    real = os.path.realpath(env)
    if real not in [os.path.realpath(a) for a in allowed]:
        die(f"{real} is not an allow-listed vault; add it to {VAULTS_FILE} as root")
    return real


def allowed_prefixes() -> list:
    """Each line is a token *prefix*, matched against argv, so `python3` on its own does
    not belong on the list while `python3 -m pytest` does. Without this the witness is
    a signing oracle for `python3 -c "print(1)"` — a real exit code from a fake test."""
    try:
        with open(ALLOWED_FILE) as fh:
            return [[t for t in l.split() if t] for l in fh
                    if l.strip() and not l.strip().startswith("#")]
    except OSError:
        return []


def permitted(argv: list) -> bool:
    """Is this argv on the allow-list, and is it the *same program* the list names?

    Matching a basename would let `/tmp/anything/pytest` through as `pytest`, which turns
    the witness into a signing oracle for whatever the caller wrote there. So the
    executable is resolved the way the child will resolve it — against `FIXED_PATH` below
    — and must land on the same file the allow-list line names.
    """
    if not argv:
        return False
    resolved = _executable(argv[0])
    if not resolved:
        return False
    for prefix in allowed_prefixes():
        if not prefix or len(argv) < len(prefix):
            continue
        if _executable(prefix[0]) != resolved or argv[1:len(prefix)] != prefix[1:]:
            continue
        return True
    return False


def _executable(name: str) -> str:
    """The absolute path a child would actually run, or "" if there is none."""
    found = shutil.which(name, path=FIXED_PATH)
    return os.path.realpath(found) if found else ""


def safe_token(value: str, what: str) -> str:
    """A bare name, and not one that walks out of the vault with `.` or `..`."""
    token = (value or "").strip()
    if not token or any(c in token for c in "/\\\0"):
        die(f"{what} must be a bare name")
    if token.startswith(".") or token in (".", ".."):
        die(f"{what} may not start with a dot: {token!r}")
    return token


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(data: dict) -> bytes:
    body = {k: v for k, v in data.items() if k != "attestation"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


def sign(data: dict) -> dict:
    if not os.path.isfile(KEY_FILE):
        die(f"attestation key missing at {KEY_FILE}")
    # `sealed_by` goes inside the signed body, not the attestation envelope: everything
    # under "attestation" is excluded from the canonical form, so metadata parked there
    # would be free for an agent to rewrite.
    body = dict(data)
    body.setdefault("sealed_by", {"uid": os.getuid(), "pid": os.getpid(),
                                  "sealed": now_iso()})
    msg = "/tmp/.brain-witness-msg.%d" % os.getpid()
    sig = "/tmp/.brain-witness-sig.%d" % os.getpid()
    try:
        with open(msg, "wb") as fh:
            fh.write(canonical(body))
        res = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", KEY_FILE,
                              "-rawin", "-in", msg, "-out", sig],
                             capture_output=True, text=True)
        if res.returncode != 0:
            die(f"signing failed: {res.stderr.strip()}")
        signature = base64.b64encode(open(sig, "rb").read()).decode("ascii")
    finally:
        for path in (msg, sig):
            try:
                os.unlink(path)
            except OSError:
                pass
    out = dict(body)
    out["attestation"] = {
        "alg": "ed25519",
        "key": hashlib.sha256(open(os.path.join(TRUST_DIR, "attest.pub"), "rb").read())
               .hexdigest()[:16],
        "sig": signature,
        "trust_mode": "installed",
    }
    return out


def write_private(path: str, text: str, mode: int = 0o644) -> None:
    """Root-owned, agent-readable, agent-unwritable. Directory ownership is what stops
    an agent unlinking or replacing a receipt.

    Only the directories the witness owns outright get sealed. `meta/` holds the
    topology an agent is still allowed to *propose* — the pin is what it cannot approve —
    so taking that directory away would stop the protocol, not the attack.
    """
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    if os.path.basename(parent) in ROOT_OWNED_DIRS:
        stat = os.stat(parent)
        if stat.st_uid != 0 or stat.st_mode & 0o022:
            os.chown(parent, 0, 0)
            os.chmod(parent, 0o755)
    tmp = path + ".witness.tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.chmod(tmp, mode)
    os.chown(tmp, 0, 0)
    os.replace(tmp, path)


def parse_flags(argv: list) -> tuple:
    flags, rest = {}, []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            rest = argv[i + 1:]
            break
        if tok.startswith("--"):
            flags[tok[2:]] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
            continue
        rest.append(tok)
        i += 1
    return flags, rest


def cmd_exec(argv: list) -> int:
    flags, command = parse_flags(argv)
    if not command:
        die("exec needs a command after --")
    # `python3 -m unittest --help` exits 0 having proved nothing. A receipt is only worth
    # signing for a run that could have failed.
    if any(tok in NO_EVIDENCE for tok in command[1:]):
        die("a help or version flag is not evidence: it exits 0 without running anything")
    task_id = safe_token(flags.get("task"), "--task")
    workspace = safe_token(flags.get("workspace") or "global", "--workspace")

    if not permitted(command):
        die(f"{command[:3]!r} is not an allow-listed command in {ALLOWED_FILE}; the "
            f"witness signs real test runs, not arbitrary programs")

    root = vault_root()
    cwd = os.path.realpath(flags.get("cwd") or root)
    if not cwd.startswith(root + os.sep) and cwd != root:
        die("--cwd must live inside the allow-listed vault")
    if not os.path.isdir(cwd):
        die(f"--cwd {cwd} is not a directory")

    try:
        timeout = min(int(flags.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT)
    except ValueError:
        die("--timeout must be an integer")

    drop_uid = int(os.environ.get("SUDO_UID", "0"))
    drop_gid = int(os.environ.get("SUDO_GID", "0"))
    if drop_uid <= 0:
        die("cannot determine the calling uid to drop privileges to")

    log_dir = os.path.join(vault_root(), "workspaces", workspace, "logs")
    os.makedirs(log_dir, exist_ok=True)
    # The name is unguessable and created O_EXCL|O_NOFOLLOW: a predictable transcript
    # name is a file the caller can pre-plant, and as root that is an arbitrary write.
    # The directory itself stays the vault's — `logs/` also holds daemon state.
    transcript = os.path.join(log_dir,
                              f"witness-{task_id}-{int(time.time())}-{os.urandom(4).hex()}.log")
    started = time.monotonic()
    env = {
        "PATH": FIXED_PATH,
        "HOME": pwd.getpwuid(drop_uid).pw_dir,
        "USER": pwd.getpwuid(drop_uid).pw_name,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "BRAIN_WITNESSED": "1",
    }
    try:
        sink_fd = os.open(transcript, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600)
        with open(sink_fd, "wb") as sink:
            proc = subprocess.Popen(
                command, cwd=cwd, env=env, stdout=sink, stderr=subprocess.STDOUT,
                preexec_fn=lambda: (os.setgid(drop_gid), os.setuid(drop_uid)),
                start_new_session=True,
            )
            try:
                exit_code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = 124
    except OSError as exc:
        die(f"could not run {command[0]!r}: {exc}")

    raw = open(transcript, "rb").read(MAX_OUTPUT_BYTES + 1)
    if len(raw) > MAX_OUTPUT_BYTES:
        die(f"command produced more than {MAX_OUTPUT_BYTES} bytes of output; "
            f"refusing to record a truncated transcript")
    text = raw.decode("utf-8", errors="replace")
    caller = pwd.getpwuid(drop_uid).pw_name

    receipt = {
        "receipt_id": f"rcpt_{time.strftime('%Y%m%d')}_{int(time.time() * 1000)}_w",
        "task_id": task_id,
        "workspace": workspace,
        "session_id": flags.get("session", ""),
        "command": " ".join(shlex.quote(c) for c in command),
        "argv": command,
        "exit_code": int(exit_code),
        "stdout": text,
        "stderr": "",
        "stdout_hash": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        "stderr_hash": hashlib.sha256(b"").hexdigest(),
        "transcript_path": transcript,
        "transcript_sha256": hashlib.sha256(raw).hexdigest(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "timestamp": now_iso(),
        "recorded_at": time.time(),
        "cwd": cwd,
        "requested_by": caller,
        "witnessed_by": "brain-witness",
        "verified": int(exit_code) == 0,
    }
    signed = sign(receipt)
    out = os.path.join(vault_root(), "workspaces", workspace, "receipts",
                       f"{receipt['receipt_id']}.json")
    os.chmod(transcript, 0o644)
    os.chown(transcript, 0, 0)
    write_private(out, json.dumps(signed, indent=2, default=str) + "\n")
    print(json.dumps(signed, indent=2, default=str))
    return 0 if exit_code == 0 else 1


def cmd_pin_topology(argv: list) -> int:
    """Sign the hash of a workspace topology. Requires a password, so an agent cannot
    rewrite its own routing policy and then legitimise the rewrite."""
    flags, _ = parse_flags(argv)
    workspace = safe_token(flags.get("workspace"), "--workspace")
    path = os.path.join(vault_root(), "workspaces", workspace, "meta", "topology.yaml")
    if not os.path.isfile(path):
        die(f"no topology at {path}")
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    record = sign({
        "kind": "topology-pin",
        "workspace": workspace,
        "sha256": digest,
        "timestamp": now_iso(),
        "pinned_by_uid": int(os.environ.get("SUDO_UID", "0")),
        "note": flags.get("note", ""),
    })
    write_private(os.path.join(vault_root(), "workspaces", workspace, "meta",
                               "topology.pin.json"),
                  json.dumps(record, indent=2, default=str) + "\n")
    print(f"pinned {workspace} topology at sha256={digest[:16]}…")
    return 0


def cmd_grant_bypass(argv: list) -> int:
    """Mint a single-use, time-boxed bypass grant. Password-gated by design: this is
    the human authorising an agent to step outside the boundary, so it cannot be minted
    from inside that boundary."""
    flags, _ = parse_flags(argv)
    reason = (flags.get("reason") or "").strip()
    seat = safe_token(flags.get("seat"), "--seat")
    if len(reason) < 10:
        die("--reason is required and must explain the emergency (>= 10 chars)")
    if not seat:
        die("--seat is required: name the one seat this grant applies to")
    try:
        minutes = min(int(flags.get("minutes") or 30), 240)
    except ValueError:
        die("--minutes must be an integer")
    nonce = os.urandom(16).hex()
    grant = {
        "kind": "bypass-grant",
        "grant_id": f"grant_{nonce[:12]}",
        "nonce": nonce,
        "seat": seat,
        "reason": reason,
        "issued": now_iso(),
        "expires": (datetime.now(timezone.utc) + timedelta(minutes=minutes))
                   .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "authorised_by_uid": int(os.environ.get("SUDO_UID", "0")),
        "single_use": True,
    }
    signed = sign(grant)
    # 0644, not 0600: the seat has to read its own grant to present it. Root ownership
    # is what makes it unforgeable and unwritable; the secret was never the file, it is
    # the key that signed it.
    write_private(os.path.join(vault_root(), "grants", f"{grant['grant_id']}.json"),
                  json.dumps(signed, indent=2, default=str) + "\n")
    sys.stderr.write(f"grant {grant['grant_id']} valid for {minutes}m for seat {seat}\n")
    print(signed["attestation"]["sig"] + "." + nonce)
    return 0


def cmd_spend_grant(argv: list) -> int:
    """Move a grant out of the live set. NOPASSWD by design, and one-directional: an
    agent may close a door that was opened for it, but only a password opens a new one.

    Without this, `grants/` being root-owned — which is the point of it — would leave the
    holder unable to consume its own grant, and every gate would see a live record
    forever.
    """
    flags, rest = parse_flags(argv)
    grant_id = safe_token(rest[0] if rest else flags.get("grant"), "grant id")
    directory = os.path.join(vault_root(), "grants")
    path = os.path.join(directory, f"{grant_id}.json")
    if not os.path.isfile(path):
        die(f"no grant {grant_id} on record (already spent?)")
    used = os.path.join(directory, "used")
    os.makedirs(used, exist_ok=True)
    os.chown(used, 0, 0)
    os.chmod(used, 0o700)
    os.replace(path, os.path.join(used, f"{grant_id}.json"))
    # A spent record still carries a live-looking signature; only an unspent grant needs
    # to be readable by the seat it was minted for.
    os.chmod(os.path.join(used, f"{grant_id}.json"), 0o600)
    os.chown(os.path.join(used, f"{grant_id}.json"), 0, 0)
    sys.stderr.write(f"grant {grant_id} spent\n")
    return 0


def main(argv: list) -> int:
    global _VAULT
    if len(argv) < 2:
        die("usage: brain-witness {exec|spend-grant|pin-topology|grant-bypass} [...]")
    require_root()
    _VAULT = (parse_flags(argv[2:])[0].get("vault") or "").strip()
    command = argv[1]
    if command == "exec":
        return cmd_exec(argv[2:])
    if command == "spend-grant":
        return cmd_spend_grant(argv[2:])
    if command == "pin-topology":
        return cmd_pin_topology(argv[2:])
    if command == "grant-bypass":
        return cmd_grant_bypass(argv[2:])
    if command == "status":
        print(json.dumps({"key": os.path.isfile(KEY_FILE),
                          "vaults": open(VAULTS_FILE).read().split()
                          if os.path.isfile(VAULTS_FILE) else [],
                          "allowed": [" ".join(p) for p in allowed_prefixes()]}, indent=2))
        return 0
    die(f"unknown subcommand {command!r}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
