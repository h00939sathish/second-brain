# Trust Model & Execution Boundary

**Document Version:** 2.0.0
**Authority:** Local Agent Control Plane
**Audience:** the human operator, and any agent that is about to trust a gate it can see.

Version 1.0.0 of this document described a wall. There is no wall. What this machine
actually has is a set of checks that hold honest agents in place, plus one small region
of real cryptography that is only as strong as a root-owned install you have not done
yet. Version 2.0.0 describes that honestly, because an agent that believes the boundary
is real where it is only advisory will report a gate as a guarantee.

---

## 1. The one fact everything else follows from

Every agent on this host runs as the same user: uid 1000 (`h00939`). The vault, the
engine, the `brain` python package, the CLI shim on `PATH`, the generated hooks in
`~/.config/git/hooks` and the agent config files that call them are all owned by that
uid and writable by it.

Consequence: **any gate an agent can execute, that agent can also decline to execute,
edit, or delete.** A check that runs inside the same process — or the same uid — as the
thing it is policing is advisory. It stops accidents, drift and laziness. It does not
stop intent.

Nothing in `brain/` should therefore be described as "enforced" without saying enforced
*against whom*. The honest categories are:

| Kind | Who it stops | Who it does not stop |
|---|---|---|
| In-process gate (`coordination.admit`, `review gate`, `topology.can_route`, `grants.bypass`) | an agent using the CLI honestly, and one that forgot | an agent that imports `brain.*` and skips the check, or edits the check |
| Filesystem advisory lock (`paths.FileLock`) | two processes racing by accident | anything that ignores the lock |
| The git hooks (`~/.config/git/hooks`) | a commit made in a bound repo with no session | anyone with `--no-verify`, or write access to the hook file (everyone at uid 1000) |
| ed25519 attestation (`brain/attest.py`) | forgery of a receipt, **once the root install is real** | in bootstrap mode, an agent that mints its own key — see §5 |

The last row is the only one with teeth outside the trust domain, and it has teeth only
because a root-owned key at `/etc/second-brain/attest.key` (mode 0600) is unreadable at
uid 1000. There is no such file on this machine today.

---

## 2. Why the pipeline is still worth having

The four-stage shape is not decoration; it is what makes an agent's claim *checkable*
even when nothing stops the agent from making it.

```
1. PROPOSE     worker states an intent            -> untrusted input, always
2. AUTHORIZE   engine applies policy               -> advisory to a dishonest caller
3. OBSERVE     a process records what the OS said  -> the interesting half
4. RECORD      the decision and the observation go to the event stream
```

The value is at 3 and 4: an assertion about the future is free, and a hash of output an
agent already produced is hard to reconcile with a lie. `verify_task` refuses a card
whose only evidence is a hand-written `test_status`, and a `--test-status` with no
receipt on file is reported as fabricated rather than waved through.

---

## 3. The five trust zones

Defined in `brain/const.py` and assigned by `const.zone_for_path()`. The workspace is not
one trust blob: what a zone permits, and who may change it, is the point of splitting it.

| Zone | const | What lives there | Who may write it | How a violation surfaces |
|---|---|---|---|---|
| CODE | `code` | `brain/`, `tests/`, `src/`, `tools/`, `mcp/`, any `.py` | an agent holding a lease on that path | `evidence.check_working_tree` compares the tree against the session's leases at close-out; the tree is the registered workspace's own — a `cwd` outside it is refused by name and a `cwd` inside it never picks the tree |
| STATE | `state` | `workspaces/<slug>/{tasks,sessions,claims,context}` and anything unclassified | the engine, on behalf of a session — not by hand | hand edits have no session behind them; `doctor` and the record's provenance say so |
| EVIDENCE | `evidence` | `receipts/`, `logs/` (transcripts), `messages/` | only the witness, once installed | `attest.verify()` returns `forged` / `unsigned`; `transcript_intact()` recomputes the hash |
| POLICY | `policy` | `meta/`, `grants/`, `topology.yaml`, `topology.pin.json` | a human, via a pinned signature | `topology.load()` raises when the file on disk no longer hashes to its pin |
| TRANSIENT | `transient` | `.obsidian/`, `.lock`, `*.tmp`, `.gitignore` | anyone, no justification required | n/a |

Zone EVIDENCE is why `workspaces/**` is excluded from the git-comparison in
`check_working_tree`: the brain writes cards, sessions and receipts constantly, so a
working-tree diff would drown in its own bookkeeping. Those zones are judged by something
sharper instead — attestation and recomputed digests — and `zone_for_path` is what keeps
that exclusion from also excusing source files.

---

## 4. What is cryptographically enforced, and what is policy-enforced

**Real cryptography (as designed, and only with the root install present):**

- `brain/attest.py` signs records ed25519 through the `openssl` CLI. Private key
  `/etc/second-brain/attest.key`, root-owned mode 0600; public key world-readable so
  every agent can verify. Once the anchor is installed, signing additionally requires
  euid 0 — so from an agent process `sign()` refuses and `verify()` works, and the
  witness is the only thing that can produce a receipt.
- The trust anchor is the root-owned `/etc/second-brain/attest.fpr`.
  `trust_root_ok()` compares the fingerprint of the public key actually in use against
  it, so a vault-local key cannot masquerade as the operator's. `_trust_dir()` is
  deliberately not overridable by environment variable: if `BRAIN_ATTEST_TRUST_DIR`
  worked, an agent would point verification at its own key and the boundary would be
  decorative.
- `tools/brain-witness.py` is a root process installed at `/usr/local/bin/brain-witness`
  and never imported from the vault — an agent owns every file under the vault, so
  anything the witness imported from there would make "run the witness" equivalent to
  local root. `exec` runs an **allow-listed** command
  (`/etc/second-brain/allowed-commands`) as the *calling* uid from `SUDO_UID`/`SUDO_GID`,
  observes the real exit code, captures the transcript itself, hashes it, signs the
  receipt and writes it root-owned into an allow-listed vault
  (`/etc/second-brain/vaults`). `exec` is NOPASSWD so agents can produce genuine
  evidence; `pin-topology` and `grant-bypass` demand a password, so only a human can
  change routing policy or authorise a bypass.
- `brain/topology.py` refuses to load a `topology.yaml` whose sha256 does not match a
  signed `meta/topology.pin.json`.

**Policy-enforced only (real checks, no adversary):**

- Lease and session clearance (`coordination.admit`, `brain guard`), the review gate, card
  custody (`board.may_speak_for`), the task and claim state machines, the routing graph's
  shape, workspace scoping.
- `topology.can_route` is fail-*closed* within its scope: inside a declared topology an
  undeclared seat or a missing edge is DENY, and self-routing is not exempt. A denial is
  paid over only by a human-minted grant, which is spent on the attempt so it buys one
  step and nothing else. A workspace with no `topology.yaml` has no policy to enforce:
  routing is allowed and the event stream gets `ROUTING_UNGOVERNED`. That is a
  configuration gap being announced, not a hole being papered over.
- The event stream is append-only by construction and **not signed** (`events.emit`
  appends JSONL and swallows `OSError`). INV-005's guarantee is completeness-of-form, not
  unforgeability.
- The git hooks in `~/.config/git/hooks`. See §7.

`evidence.verify_task` is where the two kinds meet, and it now insists on the
cryptographic one: a receipt must be `VERIFIED`, the exit code must be 0, and the bound
transcript must still hash to what was signed. The branch where a named reviewer's
sign-off alone cleared the gate has been deleted — a reviewer is another uid-1000 agent,
so their word was never the missing evidence.

---

## 5. Two trust modes, and which defences need the first one

`attest.mode()` reports which is live; `brain attest` prints it, `brain doctor` flags it.

**`installed`** — a root-owned `/etc/second-brain/attest.fpr` anchor exists. Agents can
verify receipts and structurally cannot forge them. `attest.sign()` raises unless
euid 0, so `evidence.record_receipt()` called in-process raises `PermissionError` and
forces the request through `brain test` → `brain-witness`.

**`bootstrap`** — no anchor. The vault mints its own keypair under `.trust/` and signs
with it, and every receipt carries `trust_mode: bootstrap`, which reads exactly as
"signed, but any agent could have signed it". `evidence.witness_available()` is false, so
execution is observed in-process. Gates that would otherwise lock the machine shut
continue to work — refusing `BRAIN_BYPASS=1` before a human can mint a grant would
protect nothing and cost everything.

**This host is in `bootstrap` right now**: `/etc/second-brain` and
`/usr/local/bin/brain-witness` do not exist.

Be precise about what the key buys, because it is less than "tamper-proof". After the
root install, an agent at uid 1000 still cannot *add* or *alter* a receipt with a valid
signature, and cannot make a tampered transcript verify. It can still delete a receipt
file — and the gate then fails closed with "no execution receipt recorded", which is the
correct outcome for the deletion but is not the same as the evidence being
undeletable. Directory ownership under the vault is agent-owned, so unlink is available;
only the signature is not forgeable.

**Every line of defence in §4 that is called cryptographic requires the root install to
be real.** Until then the true statement about a `bootstrap` receipt is: *an
independent process ran this command and recorded its exit code* — which is worth having
and worth labelling, and is not a boundary.

---

## 6. Break glass

Two different things, and the difference is who authorised it.

- `BRAIN_BYPASS=1` — any process at uid 1000 can set it, so it authorises nothing. It is
  honoured **only in bootstrap mode**, by every gate that consults
  `paths.bypass_enabled()`, and each of those writes `BYPASS_SELF_GRANTED` to the event
  stream so the audit trail says who let the work through: the caller.
  `brain/agents.py` and the git hooks are not allowed to advertise it as a general
  escape hatch.
- `brain bypass-grant --seat <seat> --reason "..." [--minutes N]` — the
  human-authorised path. It shells out to `sudo brain-witness grant-bypass`, which
  requires a password, and returns a token carried in `$BRAIN_BYPASS_GRANT`:
  single-use, bound to one seat, expiring (default 30 minutes, capped at 240), and moved
  to `grants/used/` on first spend. Once trust is installed this is the only thing that
  steps over the line, and `BRAIN_BYPASS=1` stops working everywhere including the commit
  hook.

A grant cannot be minted today: there is no witness binary, and
`cmd_bypass_grant` says so rather than pretending to succeed.

---

## 7. The git hooks specifically

`~/.config/git/hooks/{pre-commit,post-commit}` are installed globally via
`core.hooksPath`, so they run in **every** repository this user touches, including ones
the brain has never heard of. They resolve the engine from `$SECOND_BRAIN_ENGINE`, then
`/mnt/shared/projects/second-brain/engine.py`, then `$HOME/Work/second-brain/engine.py`,
and warn-and-exit-0 when none exists: a recorder that is merely broken must never wedge
the VCS.

The guard binds a repository the operator pointed at the brain (`git config
brain.project`, `git config brain.workspace`, or a `.brain-workspace` marker). An
unbound repository is one the brain was never asked about, which is not the same as
being told no — the same rule `topology.can_route` follows.

These hooks are advisory in the strongest sense: they are plain files writable by every
agent they appear to police, and `git commit --no-verify` is one flag away. Treat them as
a reminder to honest callers, not as the trust boundary.

---

## 8. Residual risks accepted

Stated as accepted, not as open questions. All three are reachable today by an agent that
tries.

1. **Identity is theft-prone.** A process at uid 1000 can read `/proc/<pid>/environ` of
   any other agent process and lift `BRAIN_AGENT`, then present itself as that seat.
   `_agent()` refuses a `--agent` that contradicts the declared seat, which stops an
   agent lying *out loud* and stops nothing else. Seat binding is a labelling
   convenience, not authentication.
2. **The CLI is a suggestion.** `brain` is a python package inside an agent-writable
   tree. Importing `brain.coordination` directly, or calling `store.write_record`, skips
   every argparse-level check. The gates live in the functions too, but so does the code
   that decides whether to call them.
3. **Bootstrap signatures are unforgeable by nobody.** Without the root anchor, an agent
   can mint its own ed25519 keypair under `.trust/`, tamper with a receipt, re-sign it
   with its own key, and `attest.verify()` reports `verified` — because verification
   checks the signature against *the public key in use*, and "in use" is attacker-chosen
   in bootstrap mode. The hostile probe that demonstrates this
   (`tests/hostile/test_trust_boundary.py`, the re-sign-with-the-vault-key case) is
   deliberately a **pass**: the defence it tests is the label
   `trust_mode: bootstrap`, not the signature. X6b proved the attack; nothing in the
   current code stops it, and nothing in-process can.

Also true, in the same category: the event stream is unsigned (§4), an agent can delete
evidence it cannot alter (§5), and the global git hooks can be edited by any agent that
is bothered by them (§7).

Closing 1–3 requires work outside the vault: separate uids or containers per agent for 1
and 2, and the root-owned trust anchor plus `/usr/local/bin/brain-witness` for 3.

---

## 9. What an operator should actually check

```bash
brain attest                              # mode: installed | bootstrap, fingerprint, witness?
brain doctor                              # unbound workspaces, drift, unspent grants, index
brain topology validate -w <ws>           # is routing governed here, and is it the pinned policy?
brain grants                              # unspent bypass grants, and what they attest to
brain verify-invariants                   # INV-001..INV-008, the honest-use suite
brain verify-boundary                     # the adversarial tier: can a dishonest agent win?
```

`brain verify-boundary` is the one that tells you how much of this document is still true
today. Measured on this host: `10/11 probes blocked, 1 known-open`, and the known-open probe
is `p1` — identity, §8.1. The honest suite reads `Ran 259 tests ... OK
(expected failures=1)`, and that one expected failure is the same probe. A unit suite going
green means the code does what it says when used honestly.

Related: `INVARIANTS.md` (the constitutional rules), `EVENT_MODEL.md` (the log schema),
`STATE_MACHINES.md`, `CONTROL_PLANE_AUDIT.md` (how the code was found), `ROADMAP.md`.
