# -*- coding: utf-8 -*-
"""Runtime-held attestation: an agent may run anything, only the runtime may say it ran.

Ed25519 via the openssl CLI so the vault keeps zero python dependencies. The private
key is root-owned and mode 0600; every agent on this host runs as uid 1000 and cannot
read it, so a signature is something an agent can verify but cannot manufacture.

Signing additionally requires euid 0, which keeps this module safe to call from an
agent process: `sign()` refuses, `verify()` works.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .paths import VAULT

TRUST_DIR = Path("/etc/second-brain")
KEY_NAME = "attest.key"
PUB_NAME = "attest.pub"
FPR_NAME = "attest.fpr"
VAULT_TRUST_DIR = ".trust"

VERIFIED = "verified"
FORGED = "forged"
UNSIGNED = "unsigned"
NO_TRUST_ROOT = "no_trust_root"

ATTEST_FIELD = "attestation"


def _trust_dir() -> Path:
    """Where the operator's key material lives. Not overridable by a plain process
    env var: if BRAIN_ATTEST_TRUST_DIR could redirect this, an agent could point
    verification at its own key and the whole boundary would be decorative."""
    return TRUST_DIR


def installed() -> bool:
    """True once the operator has run the trust install: a root-owned anchor exists."""
    return (_trust_dir() / FPR_NAME).is_file()


def mode() -> str:
    """installed = a root-owned anchor exists and agents cannot mint keys.
    bootstrap   = no anchor yet; the vault signs with a key the agents can read, so
    every gate must report that it is not a real boundary."""
    return "installed" if installed() else "bootstrap"


def _vault_trust_dir() -> Path:
    return VAULT / VAULT_TRUST_DIR


def public_key_path() -> Path:
    if installed():
        authority = TRUST_DIR / PUB_NAME
        mirror = _vault_trust_dir() / PUB_NAME
        if mirror.is_file() and fingerprint(mirror) == fingerprint(authority):
            return mirror
        return authority
    return _vault_trust_dir() / PUB_NAME


def private_key_path() -> Path:
    if installed():
        return TRUST_DIR / KEY_NAME
    return _vault_trust_dir() / KEY_NAME


def ensure_bootstrap_keypair() -> bool:
    """Create a vault-local keypair so the engine is usable before the operator
    installs real trust. Returns False when there is nothing to do."""
    if installed():
        return False
    directory = _vault_trust_dir()
    key = directory / KEY_NAME
    if key.is_file():
        return False
    directory.mkdir(parents=True, exist_ok=True)
    res = _openssl(["genpkey", "-algorithm", "ed25519", "-out", str(key)])
    if res.returncode != 0:
        raise RuntimeError(f"could not create bootstrap key: {res.stderr.strip()}")
    os.chmod(key, 0o600)
    pub = directory / PUB_NAME
    res = _openssl(["pkey", "-pubout", "-in", str(key), "-out", str(pub)])
    if res.returncode != 0:
        raise RuntimeError(f"could not create bootstrap pubkey: {res.stderr.strip()}")
    os.chmod(pub, 0o644)
    return True


def fingerprint(path: Path | None = None) -> str:
    target = path or public_key_path()
    try:
        raw = target.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]


def trust_root_ok() -> tuple[bool, str]:
    """The vault may carry a public key; the root-owned fingerprint is the authority."""
    authority = TRUST_DIR / FPR_NAME
    if not authority.is_file():
        return True, "bootstrap: no root-owned trust anchor, agents can mint their own keys"
    try:
        expected = authority.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "cannot read trust anchor"
    actual = fingerprint(public_key_path())
    if actual != expected:
        return False, (f"public key in use ({actual}) does not match the root-owned "
                       f"trust anchor ({expected})")
    return True, "ok"


def canonical(data: dict) -> bytes:
    body = {k: v for k, v in data.items() if k != ATTEST_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


def _openssl(args: list, timeout: int = 20) -> subprocess.CompletedProcess:
    binary = shutil.which("openssl")
    if not binary:
        raise RuntimeError("openssl not found on PATH; attestation is unavailable")
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout)


def sign(data: dict) -> dict:
    """Attach an ed25519 signature.

    Under an installed trust root this requires euid 0, so an agent process structurally
    cannot sign its own evidence. In bootstrap mode it signs with a vault-local key and
    stamps the record as such, because pretending to be secure is worse than admitting it.
    """
    root_ok, why = trust_root_ok()
    if not root_ok:
        raise PermissionError(f"refusing to sign: {why}")
    if installed():
        if os.geteuid() != 0:
            raise PermissionError(
                "attestation requires the privileged witness (sudo -n brain-witness exec): "
                "only the runtime may attest that a process ran. Route through `brain test`."
            )
        trust_mode = "installed"
    else:
        ensure_bootstrap_keypair()
        trust_mode = "bootstrap"
    key = private_key_path()
    if not key.is_file():
        raise FileNotFoundError(f"attestation key not available at {key}")
    with tempfile.NamedTemporaryFile(delete=False) as msg, tempfile.NamedTemporaryFile(delete=False) as sig:
        msg_path, sig_path = msg.name, sig.name
    try:
        Path(msg_path).write_bytes(canonical(data))
        res = _openssl(["pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", msg_path,
                        "-out", sig_path])
        if res.returncode != 0:
            raise RuntimeError(f"signing failed: {res.stderr.strip()}")
        import base64
        signature = base64.b64encode(Path(sig_path).read_bytes()).decode("ascii")
    finally:
        for p in (msg_path, sig_path):
            Path(p).unlink(missing_ok=True)
    out = dict(data)
    out[ATTEST_FIELD] = {"alg": "ed25519", "key": fingerprint(), "trust_mode": trust_mode,
                         "sig": signature}
    return out


def verify(data: dict) -> str:
    """VERIFIED / FORGED / UNSIGNED / NO_TRUST_ROOT — never raises on bad input."""
    att = data.get(ATTEST_FIELD)
    if not isinstance(att, dict) or not att.get("sig"):
        return UNSIGNED
    root_ok, _ = trust_root_ok()
    if not root_ok:
        return NO_TRUST_ROOT
    pub = public_key_path()
    if not pub.is_file():
        return NO_TRUST_ROOT
    import base64
    try:
        raw_sig = base64.b64decode(att["sig"], validate=True)
    except Exception:
        return FORGED
    with tempfile.NamedTemporaryFile(delete=False) as msg, tempfile.NamedTemporaryFile(delete=False) as sig:
        msg_path, sig_path = msg.name, sig.name
    try:
        Path(msg_path).write_bytes(canonical(data))
        Path(sig_path).write_bytes(raw_sig)
        res = _openssl(["pkeyutl", "-verify", "-pubin", "-inkey", str(pub), "-rawin",
                        "-in", msg_path, "-sigfile", sig_path])
    except RuntimeError:
        return NO_TRUST_ROOT
    finally:
        for p in (msg_path, sig_path):
            Path(p).unlink(missing_ok=True)
    return VERIFIED if res.returncode == 0 else FORGED


def seal_to_file(path: Path, data: dict) -> dict:
    """Sign then write atomically. Used only by the privileged witness."""
    signed = sign(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(signed, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return signed


def status() -> dict:
    return {
        "mode": mode(),
        "installed": installed(),
        "public_key": str(public_key_path()),
        "key_fingerprint": fingerprint(),
        "trust_root": trust_root_ok()[1],
        "signer_available": (os.geteuid() == 0 and private_key_path().is_file())
                            if installed() else True,
        "boundary": "real" if installed() else "none (bootstrap: agents can mint keys)",
        "openssl": shutil.which("openssl") or "",
    }
