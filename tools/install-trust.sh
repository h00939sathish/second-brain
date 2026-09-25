#!/usr/bin/env bash
# SECOND BRAIN — one-time trust install.
#
# Run this ONCE as the operator. It is the step that turns "the brain checks you" into
# "the brain cannot be forged", and it is the only step that needs a password:
#
#     sudo bash /mnt/shared/projects/second-brain/tools/install-trust.sh
#
# What it establishes:
#   * an ed25519 keypair under /etc/second-brain that no agent can read (uid 1000 does
#     not own it, mode 0600), so a signature on a receipt is not something an agent
#     can produce for itself
#   * a root-owned fingerprint anchor, attest.fpr, so swapping the *public* key is also
#     detected — without it, replacing attest.pub and re-signing everything is free
#   * /usr/local/bin/brain-witness, root-owned, which runs an allow-listed test command
#     as the agent's own uid, observes the real exit code, captures the transcript
#     itself, and seals the result into a directory the agent cannot write in
#   * sudo NOPASSWD for `brain-witness exec` (make real evidence) and `spend-grant`
#     (close a door a human opened) ONLY. `pin-topology` and `grant-bypass` deliberately
#     still demand the password, so policy changes and break-glass stay human decisions.
#
# Read it before you run it. Nothing here is destructive to existing work, and the
# script refuses to overwrite an existing private key.

set -e -u -o pipefail

VAULT="${1:-/mnt/shared/projects/second-brain}"
TRUST_DIR=/etc/second-brain
WITNESS_SRC="$VAULT/tools/brain-witness.py"
WITNESS_DST=/usr/local/bin/brain-witness
SUDOERS=/etc/sudoers.d/second-brain-witness
RUN_AS="$(logname 2>/dev/null || echo "${SUDO_USER:-}")"

say() { printf '%s\n' "$*"; }
die() { say "install-trust: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run it with sudo: the whole point is that these files are root-owned"
command -v openssl >/dev/null || die "openssl is required for attestation"
[ -f "$WITNESS_SRC" ] || die "no witness at $WITNESS_SRC"
[ -n "$RUN_AS" ] || die "cannot tell which operator this is for: the sudoers rule needs a name"
id -u "$RUN_AS" >/dev/null 2>&1 || die "no such user: $RUN_AS"

say "== trust install for $VAULT (operator: ${RUN_AS:-unknown}) =="

# --- 1. the key -------------------------------------------------------------------
mkdir -p "$TRUST_DIR"
chmod 755 "$TRUST_DIR"

if [ -f "$TRUST_DIR/attest.key" ]; then
  say "  key already present, leaving it alone: rotating it invalidates every existing receipt"
else
  umask 077
  openssl genpkey -algorithm ed25519 -out "$TRUST_DIR/attest.key" 2>/dev/null \
    || die "could not generate the keypair"
  chmod 600 "$TRUST_DIR/attest.key"
  chown root:root "$TRUST_DIR/attest.key"
  openssl pkey -in "$TRUST_DIR/attest.key" -pubout -out "$TRUST_DIR/attest.pub" 2>/dev/null \
    || die "could not export the public key"
  chmod 644 "$TRUST_DIR/attest.pub"
  chown root:root "$TRUST_DIR/attest.pub"
fi

# The anchor is what makes the *public* key non-swappable. It is compared against the
# key actually in use by brain/attest.py::trust_root_ok() — so writing a truncated or
# empty one would silently turn every genuine receipt into `no_trust_root`.
[ -s "$TRUST_DIR/attest.pub" ] || die "no public key at $TRUST_DIR/attest.pub: not touching the anchor"
FPR="$(sha256sum "$TRUST_DIR/attest.pub" | cut -c1-16)"
[ "${#FPR}" -eq 16 ] || die "fingerprint came out as '$FPR', expected 16 hex characters"
if [ -f "$TRUST_DIR/attest.fpr" ] && [ "$(cat "$TRUST_DIR/attest.fpr")" != "$FPR" ]; then
  die "the anchor names a different key than attest.pub holds. Either the key was rotated
  out from under the anchor or one of them was replaced; every existing receipt is now
  unverifiable. Settle that by hand — not by rerunning this and overwriting the anchor."
fi
printf '%s\n' "$FPR" > "$TRUST_DIR/attest.fpr"
chmod 644 "$TRUST_DIR/attest.fpr"; chown root:root "$TRUST_DIR/attest.fpr"
say "  fingerprint: $FPR"

# --- 2. which vaults the witness may write into -----------------------------------
if [ ! -f "$TRUST_DIR/vaults" ]; then
  printf '# one vault root per line; the witness refuses to write evidence anywhere else\n%s\n' "$VAULT" \
    > "$TRUST_DIR/vaults"
  chmod 644 "$TRUST_DIR/vaults"
fi
grep -qx "$VAULT" "$TRUST_DIR/vaults" 2>/dev/null || echo "$VAULT" >> "$TRUST_DIR/vaults"
say "  vaults: $(tr '\n' ' ' < "$TRUST_DIR/vaults" | tr -s ' ')"

# --- 3. what the witness will run --------------------------------------------------
# Each line is a token PREFIX matched against argv. `python3` alone is deliberately
# absent: it would make the witness a signing oracle for `python3 -c "print(1)"` —
# a genuine exit code from a test that never ran. Add your project's real test entry.
if [ ! -f "$TRUST_DIR/allowed-commands" ]; then
  cat > "$TRUST_DIR/allowed-commands" <<'LIST'
# test commands the witness will execute and attest
pytest
python3 -m pytest
python3 -m unittest
npm test
pnpm test
go test
cargo test
make test
LIST
  chmod 644 "$TRUST_DIR/allowed-commands"
  say "  wrote a starter allow-list; review $TRUST_DIR/allowed-commands"
fi

# --- 4. the witness itself ---------------------------------------------------------
# Root-owned and outside the vault on purpose. If it lived under the vault an agent
# could edit it, and NOPASSWD would then be local root.
#
# But the *source* it is copied from is agent-writable. So the installed digest is
# recorded, and a re-run that would replace the binary with different code says so
# instead of quietly granting the vault's authors a root shell. Re-run deliberately with
# ALLOW_WITNESS_CHANGE=1 after reading the diff.
WITNESS_STAMP="$TRUST_DIR/witness.sha256"
SRC_SHA="$(sha256sum "$WITNESS_SRC" | cut -d' ' -f1)"
if [ -f "$WITNESS_STAMP" ] && [ "$(cat "$WITNESS_STAMP")" != "$SRC_SHA" ] \
   && [ "${ALLOW_WITNESS_CHANGE:-}" != "1" ]; then
  die "$WITNESS_SRC changed since the last install (recorded $(cat "$WITNESS_STAMP"), now $SRC_SHA).
  Anyone who can edit the vault can edit that file, so installing it is installing their
  code as root. Read \`diff $WITNESS_DST $WITNESS_SRC\`, then rerun with ALLOW_WITNESS_CHANGE=1."
fi
install -o root -g root -m 755 "$WITNESS_SRC" "$WITNESS_DST"
printf '%s\n' "$SRC_SHA" > "$WITNESS_STAMP"
chmod 644 "$WITNESS_STAMP"; chown root:root "$WITNESS_STAMP"
say "  installed $WITNESS_DST"

# --- 5. sudoers: observing and closing, never approving -----------------------------
# Two commands, both harmless to grant passwordlessly: `exec` runs a root-listed test
# command as the *caller's* uid and reports what really happened, and `spend-grant` can
# only destroy a grant a human already minted. Writing `$RUN_AS` rather than `%wheel`
# keeps this to the account that actually runs the agents.
cat > "$SUDOERS.tmp" <<SUDOERS
# Second Brain: agents may produce genuine evidence without a password, because the
# witness runs as root only to *observe* and to drop back to the caller's uid. Policy
# (pin-topology) and break-glass (grant-bypass) are NOT in here: they need a human.
$RUN_AS ALL=(root) NOPASSWD: $WITNESS_DST exec *
$RUN_AS ALL=(root) NOPASSWD: $WITNESS_DST spend-grant *
SUDOERS
chmod 440 "$SUDOERS.tmp"
visudo -cf "$SUDOERS.tmp" >/dev/null 2>&1 || die "the sudoers fragment failed validation, not installing it"
mv "$SUDOERS.tmp" "$SUDOERS"
chown root:root "$SUDOERS"
say "  wrote $SUDOERS (NOPASSWD for \`brain-witness exec\` and \`spend-grant\` only)"

# --- 6. make the evidence directories unwritable by agents --------------------------
# Unlinking or replacing a receipt needs write permission on the *directory*, so this
# is what actually stops an agent deleting inconvenient evidence — and it is what stops a
# spent grant being moved back into the live set, which is the replay that makes a
# single-use bypass worthless.
#
# `logs/` is deliberately NOT here: the daemon keeps its own state there. Transcripts are
# protected by a name nobody can guess, a file nobody but root can create twice, and a
# re-hash at verification time (evidence.transcript_intact).
count=0
for dir in "$VAULT"/grants "$VAULT"/workspaces/*/receipts; do
  [ -d "$dir" ] || continue
  chown -R root:root "$dir" && chmod 755 "$dir" && count=$((count + 1))
done
say "  locked $count evidence director$([ "$count" = 1 ] && echo y || echo ies) as root-owned"

existing=$(find "$VAULT"/workspaces/*/receipts -name '*.json' 2>/dev/null | wc -l)
if [ "${existing:-0}" -gt 0 ]; then
  say "  NOTE: $existing pre-existing receipt(s) were sealed with the bootstrap key. They"
  say "        will now read as FORGED or UNSIGNED, which is the truth about them: any agent"
  say "        could have signed them. New evidence is unforgeable."
fi

# --- 7. prove it -------------------------------------------------------------------
# Every probe below is run as the operator, not as root, because the question is what an
# agent process can and cannot do.
say "\n== verifying as $RUN_AS =="
sudo -u "$RUN_AS" env SECOND_BRAIN_VAULT="$VAULT" python3 "$VAULT/engine.py" attest \
  || say "  (the brain cannot see the trust root yet — read the output above)"

say "\n  this must SUCCEED — a real test run, attested with no password:"
sudo -u "$RUN_AS" sudo -n "$WITNESS_DST" exec --task install-probe --workspace global \
     --vault "$VAULT" --cwd "$VAULT" -- python3 -m unittest tests.test_topology 2>&1 | tail -4 \
  || say "  (the exec probe did not complete: check the sudoers rule and $TRUST_DIR/vaults)"

say "\n  and these must REFUSE:"
sudo -u "$RUN_AS" env VAULT="$VAULT" SECOND_BRAIN_VAULT="$VAULT" python3 -c '
import sys, os
sys.path.insert(0, os.environ["VAULT"])
from brain import attest
try:
    attest.sign({"probe": "can-an-agent-sign"})
    print("  ALLOWED — the private key is readable, the boundary is NOT real")
except Exception as exc:
    print("  refused as expected (agent signing):", str(exc)[:88])
' 2>&1 | tail -2
  sudo -u "$RUN_AS" sudo -n "$WITNESS_DST" exec --task install-probe --workspace global \
       --vault "$VAULT" --cwd "$VAULT" -- python3 -m unittest --help 2>&1 | tail -2 \
    | sed 's/^/  no-op run: /'

say "\ndone. Pin the topology you just approved with:"
say "  sudo $WITNESS_DST pin-topology --workspace <slug> --vault $VAULT --note \"v1\""
