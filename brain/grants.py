# -*- coding: utf-8 -*-
"""Human-authorised, single-use bypass grants.

Stepping outside the trust boundary has to be a decision a *person* made. A bare
``BRAIN_BYPASS=1`` is setable by any process at uid 1000, so it authorises nothing.
A grant is minted by the privileged witness behind a password
(``sudo brain-witness grant-bypass``), is bound to one seat, expires, and is destroyed
on first use so it cannot be replayed.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import attest, const
from .paths import VAULT

GRANT_KIND = "bypass-grant"
TOKEN_ENV = "BRAIN_BYPASS_GRANT"
# No override: a $BRAIN_WITNESS the holder controls is a $BRAIN_WITNESS=/bin/true, and
# the spend that reports back is the only thing making a grant single-use.
WITNESS = const.WITNESS_BINARY


def grants_dir() -> Path:
    return VAULT / const.GRANTS_DIR


def _used_dir() -> Path:
    return grants_dir() / "used"


def parse_token(raw: str = "") -> tuple:
    """Split the ``signature.nonce`` string the witness printed."""
    token = (raw or os.environ.get(TOKEN_ENV) or "").strip()
    if not token or "." not in token:
        return "", ""
    sig, _, nonce = token.rpartition(".")
    return sig.strip(), nonce.strip()


def find(nonce: str) -> tuple:
    """(record, path) for a live grant, or (None, None).

    The path is returned beside the record, never inside it: the signed body is hashed
    field by field, so a bookkeeping key parked in the record fails its own attestation.
    """
    if not nonce:
        return None, None
    for path in sorted(grants_dir().glob("grant_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("nonce") or "") == nonce:
            return data, path
    return None, None


def _expired(grant: dict) -> bool:
    stamp = str(grant.get("expires") or "")
    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return when <= datetime.now(timezone.utc)


def check(seat: str = "", raw_token: str = "") -> tuple[bool, str]:
    """Does this process carry a live grant for *seat*? Says nothing about spending it."""
    sig, nonce = parse_token(raw_token)
    if not nonce:
        return False, f"no grant token in ${TOKEN_ENV}"
    if not sig:
        return False, (f"token carries no signature: a grant is handed over as "
                       f"<signature>.<nonce>, and the record alone proves nothing")
    grant, _ = find(nonce)
    if not grant:
        return False, f"no grant with nonce {nonce[:8]}… on record (already spent?)"
    if grant.get("kind") != GRANT_KIND:
        return False, f"record is a {grant.get('kind')!r}, not a bypass grant"
    state = attest.verify(grant)
    if state != attest.VERIFIED:
        return False, f"grant signature is {state}"
    if str(grant.get(attest.ATTEST_FIELD, {}).get("sig") or "") != sig:
        return False, "grant token does not match the record on disk"
    if _expired(grant):
        return False, f"grant expired at {grant.get('expires')}"
    bound = str(grant.get("seat") or "")
    if not seat or bound != seat:
        return False, f"grant is bound to seat {bound!r}, not {seat or '(none given)'}"
    return True, f"grant {grant.get('grant_id')} for {bound}: {grant.get('reason')}"


def check_or_explain(seat: str = "", raw_token: str = "") -> tuple[bool, str]:
    """`check()`, plus the bootstrap case spelled out so the caller cannot guess."""
    if not attest.installed():
        return False, ("bootstrap trust: grants are minted by the privileged witness, "
                       "which is not installed yet")
    return check(seat, raw_token)


LEGACY_ENV = "BRAIN_BYPASS"


def bypass(seat: str = "", action: str = "", workspace: str = "",
           spend: bool = True) -> tuple[bool, str]:
    """The one question every gate asks: may this process step outside the boundary?

    With trust installed the only answer is a live signed grant, burned as it is used.
    In bootstrap mode a bare ``BRAIN_BYPASS=1`` still works — nothing can mint a grant
    without the witness, so refusing would lock the machine out rather than protect it —
    and it is written to the event stream as exactly what it is: self-granted.
    """
    seat = seat or os.environ.get("BRAIN_AGENT", "").strip()
    if attest.installed():
        return consume(seat, action=action, workspace=workspace) if spend \
            else check(seat)
    if os.environ.get(LEGACY_ENV) == "1":
        _emit("BYPASS_SELF_GRANTED", seat or "?", action, workspace,
              f"{LEGACY_ENV}=1 with no trust root: the caller authorised itself")
        return True, f"{LEGACY_ENV}=1 (bootstrap: self-granted, no human in the loop)"
    return False, f"no {LEGACY_ENV} and no trust root to verify a grant against"


def _retire(grant: dict, path: Path) -> tuple[bool, str]:
    """Take the record out of the live set.

    Normally only root can do this: `grants/` is root-owned precisely so no agent can
    restore, edit or replay a record — which also means the holder cannot spend one alone.
    So the witness does it, and if neither path works the grant is not honoured. A bypass
    that cannot be closed is not single-use.
    """
    try:
        used = _used_dir()
        used.mkdir(parents=True, exist_ok=True)
        path.replace(used / path.name)
        return True, ""
    except OSError:
        pass

    grant_id = str(grant.get("grant_id") or path.stem)
    if not grant_id or any(c in grant_id for c in "/\\\0") or grant_id.startswith("."):
        return False, f"grant id {grant_id!r} is not a bare name"
    argv = ["sudo", "-n", WITNESS, "spend-grant", "--vault", str(VAULT), grant_id]
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"cannot reach the witness to spend the grant: {exc}"
    if res.returncode != 0:
        return False, ("the witness refused to spend the grant: "
                       + (res.stderr or res.stdout or f"exit {res.returncode}").strip())
    return True, ""


def consume(seat: str = "", raw_token: str = "", action: str = "",
            workspace: str = "") -> tuple[bool, str]:
    """Consume the grant. One use, then it is gone whatever it bought."""
    ok, why = check(seat, raw_token)
    if not ok:
        _emit("BYPASS_DENIED", seat, action, workspace, why)
        return False, why
    grant, path = find(parse_token(raw_token)[1])
    if not grant:
        why = "grant disappeared between check and spend"
        _emit("BYPASS_DENIED", seat, action, workspace, why)
        return False, why
    spent, err = _retire(grant, path)
    if not spent:
        _emit("BYPASS_DENIED", seat, action, workspace, err)
        return False, err
    os.environ.pop(TOKEN_ENV, None)
    _emit("BYPASS_GRANTED", seat, action, workspace, why,
          {"grant_id": grant.get("grant_id"), "reason": grant.get("reason"),
           "expires": grant.get("expires"), "authorised_by_uid": grant.get("authorised_by_uid")})
    return True, why


def _emit(kind: str, seat: str, action: str, workspace: str, detail: str,
          extra: dict = None) -> None:
    from . import events
    payload = {"action": action, "seat": seat, "detail": detail}
    payload.update(extra or {})
    try:
        events.emit(kind, stage="AUTHORIZE", workspace=workspace, actor=f"grant:{seat or '?'}",
                    payload=payload)
    except Exception:
        pass


def list_grants() -> list:
    """Unspent grants on record, with how far they can be trusted."""
    out = []
    for path in sorted(grants_dir().glob("grant_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "grant_id": data.get("grant_id"), "seat": data.get("seat"),
            "reason": data.get("reason"), "expires": data.get("expires"),
            "attestation": attest.verify(data), "expired": _expired(data),
        })
    return out


def status(workspace: str = "") -> dict:
    seat = os.environ.get("BRAIN_AGENT", "").strip()
    ok, why = check_or_explain(seat)
    return {"carries_grant": ok, "detail": why, "seat": seat,
            "unspent": len(list_grants()), "trust_mode": attest.mode()}
