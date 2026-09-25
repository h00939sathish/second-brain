# -*- coding: utf-8 -*-
"""Adversarial regression tier for the Second Brain trust boundary.

The unit suite answers "does the code do what it says when used honestly?". This tier
answers the only question the trust model cares about: **can a dishonest agent inside
the trust domain defeat it?** Every probe is a live attack, attempted the way an
attacker attempts it — through the public `brain.*` python API or the `brain` CLI — and
each test names the specific defence it expects to fire. Nothing is stubbed out: the
vault is a throwaway temp directory (`tests.harness`, imported first because
`brain.paths.VAULT` is resolved at import time), the trust root is whatever this host
actually has installed, and the assertions run against real signed records on real disk.

Probe -> attack-path mapping:

  p1  -> attack 1   forge identity (`BRAIN_AGENT` / `--agent` of another seat)
  p2  -> attack 2   write into another agent's inbox, bypassing messaging policy
  p3  -> attack 3   edit `topology.yaml` to grant yourself a routing edge
  p4  -> attack 4   use `BRAIN_BYPASS=1` as a universal key
  p5  -> attack 5   self-mark a card `done` with no evidence
  p6  -> attack 6   manufacture a passing receipt from an asserted exit code
  p7  -> attack 7   tamper with a sealed receipt
  p8  -> attack 8   tamper with a transcript after it was sealed
  p9  -> attack 9   race / double-claim a task; move another seat's card
  p10 -> attack 10  escape the registered workspace filesystem
  p11 -> bonus      the honest path still works (no "security" bought by breakage)
  p12 -> attack 12  speak as another session's seat at the evidence gate, and present a
                    bypass grant (spend it, replay it, hand over half of it)
  p13 -> attack 13  defeat the privileged authority file rather than the code that reads
                    it: a look-alike `pytest` in front of the witness allow-list, and
                    `rm meta/topology.pin.json` instead of editing the pinned policy

A probe that cannot pass without changing product code is marked
`@unittest.expectedFailure`, so the build stays green and the hole stays visible. It is
never deleted and never softened into a false pass. When the product catches up, the
probe reports an unexpected success: that is the signal to delete the *decorator* and
nothing else — the assertions already describe the contract.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import unittest
import uuid
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import tests.harness as h  # noqa: E402  (must precede any `brain` import: vault redirect)

from brain import (attest, board, const, coordination, events, evidence,  # noqa: E402
                   grants, messaging, paths, topology, workspaces as ws_mod)
from brain.errors import (BrainError, LeaseConflict, ReviewGate, TopologyError,  # noqa: E402
                          UnverifiedEvidenceError)

# Environment variables that would leak a privilege between probes. `os.environ` is
# process-global and unittest does not isolate it, so every test starts clean and ends
# clean or a later probe inherits a bypass it never asked for. `$SECOND_BRAIN_VAULT` is
# deliberately absent: the harness sets it once at import time and the real vault is
# what a process would fall back to without it.
SENSITIVE_ENV = ("BRAIN_BYPASS", "BRAIN_BYPASS_GRANT", "BRAIN_AGENT",
                 "SECOND_BRAIN_WORKSPACE")


def _scrub_env():
    for key in SENSITIVE_ENV:
        os.environ.pop(key, None)


def _iso(stamp: datetime) -> str:
    """The wire format `grants._expired` parses and the witness writes."""
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


class HostileCase(unittest.TestCase):
    """Common scaffolding: a clean throwaway vault and workspace per probe."""

    def setUp(self):
        _scrub_env()
        h.reset_vault()
        self.slug = h.fresh_workspace("hostile")
        self.root = Path(ws_mod.entry(self.slug).get("path")).resolve()
        self.ws_meta = ws_mod.workspace_dir(self.slug) / const.META_DIR
        self.task = board.create_task("Hostile probe card", workspace=self.slug,
                                      agent="opencode", status="running")

    def tearDown(self):
        _scrub_env()

    # ---- the trust root, which this host does not have --------------------------------

    @contextlib.contextmanager
    def _installed_trust(self):
        """Simulate the root-owned install, so the code that only runs *after* it can be
        probed at all.

        This is the one place the tier reaches inside the module, and it reaches for the
        environment, never for the defence: `attest.installed()` cannot be turned on
        without writing `/etc/second-brain/attest.fpr` as root, and once it is on the
        pubkey lookup points at `/etc/second-brain/attest.pub`, which does not exist
        either — so `verify` has to be pinned beside it or every record reads
        `no_trust_root` and the probe measures the mock instead of the gate. The logic
        under test (`grants.check`/`consume`/`_retire`, `topology.load`/`pin_status`) is
        the real code on real files on disk.
        """
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(attest, "installed", return_value=True))
            stack.enter_context(mock.patch.object(attest, "verify", return_value=attest.VERIFIED))
            yield

    # ---- topology --------------------------------------------------------

    def _topology(self, seats: dict) -> Path:
        self.ws_meta.mkdir(parents=True, exist_ok=True)
        path = self.ws_meta / const.TOPOLOGY_FILE
        path.write_text(yaml.safe_dump({"version": "1", "seats": seats}, sort_keys=False),
                        encoding="utf-8")
        return path

    def _pin_topology(self, path: Path) -> Path:
        """Write the signed pin the way the privileged witness would (see
        tests/test_topology.py::test_topology_edited_after_its_pin_raises)."""
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pin = path.parent / topology.PIN_FILE
        record = attest.sign({"kind": "topology-pin", "workspace": self.slug,
                              "sha256": digest, "timestamp": paths.now()})
        pin.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return pin

    # ---- sessions and evidence ------------------------------------------

    @contextlib.contextmanager
    def _as(self, seat: str):
        """Act from a declared seat, the way an honest agent runs.

        Probes that attack identity deliberately seat themselves as the impostor; every
        other probe uses this so a refusal can never be blamed on an unseated caller.
        """
        previous = os.environ.get("BRAIN_AGENT")
        os.environ["BRAIN_AGENT"] = seat
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("BRAIN_AGENT", None)
            else:
                os.environ["BRAIN_AGENT"] = previous

    def _lease(self, agent="opencode", files="src/auth.py", task_id=None):
        with self._as(agent):
            return coordination.start(agent=agent, workspace=self.slug,
                                      task_id=task_id or self.task["id"], files=files)

    def _handoff(self, session_id, agent_holder="opencode", target="agy",
                 test_status="pytest: 12 passed in 0.4s"):
        """End a session the honest way: a finished session with a test claim, which is
        what satisfies `board.review_evidence` — so a later refusal is provably about
        the *evidence* gate and not about a missing review."""
        with self._as(agent_holder):
            coordination.end(session_id, summary="probe session", workspace=self.slug,
                             target_agent=target, test_status=test_status)

    def _clean_tree(self):
        """Prove the working-tree gate is not what is refusing a verdict.

        `verify_task` consults `check_working_tree` *before* it looks at any receipt and
        returns early with 'working tree contains changes outside session lease'. The
        registered workspace path here is not a git repository, so the tree check is a
        no-op; assert this so no probe can pass for the masked reason.
        """
        clean, outside = evidence.check_working_tree(self.slug, leased_files=[])
        self.assertTrue(clean, f"probe setup leaked a dirty tree: {outside}")

    def _repo(self, directory: Path) -> Path:
        """A git repo with no commits: `check_working_tree` then reports every file
        inside it as changed, which is exactly the surface an attacker leases against."""
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(directory)], check=True,
                       capture_output=True, text=True)
        return directory


# =============================================================================
# attack 1 — forge identity
# =============================================================================


class TestP1ForgedIdentity(HostileCase):
    """p1 defends attack 1: set `BRAIN_AGENT` to another seat (or pass `--agent`) and
    get the brain to attribute work to that seat.

    Enforced today, and proved by the two tests below:
      * a `--agent` that contradicts the declared seat is refused outright
        (`cli._agent`, `board.may_speak_for`);
      * inside a declared topology an impostor name is not a seat, so even a successful
        claim buys no route (`topology.can_route`).
    Residual gap, kept red on purpose: a process that declares *no* seat at all still
    gets any `--agent` it types believed. Closing that needs a signed seat token.
    """

    def test_p1_contradicting_agent_flag_is_refused_and_grants_no_route(self):
        """p1 — BLOCKED: put on another seat's name, then try to act as it."""
        self._topology({"codex": {"role": "planner",
                                  "edges": [{"kind": "delegates_to", "to": "agy"}]},
                        "opencode": {"role": "builder",
                                     "edges": [{"kind": "delegates_to", "to": "agy"}]},
                        "agy": {"role": "reviewer", "edges": []}})
        os.environ["BRAIN_AGENT"] = "eve"

        # (1) Routing: an undeclared seat is not a seat. Identity is still a claim, but
        # the claim buys nothing inside a declared topology.
        allowed, why = topology.can_route("eve", "agy", workspace=self.slug)
        self.assertFalse(allowed, "an undeclared seat must not route anywhere")
        self.assertIn("not declared", why)
        allowed, why = topology.can_route("", "agy", workspace=self.slug)
        self.assertFalse(allowed, "an anonymous caller must not route anywhere")
        self.assertIn("no source agent", why)

        # (2) Action: the seat cross-check refuses to open a session as somebody else.
        with self.assertRaises(BrainError) as ctx:
            coordination.start(agent="opencode", workspace=self.slug,
                               task_id=self.task["id"], files="src/auth.py")
        self.assertIn("eve", str(ctx.exception))
        self.assertEqual([], coordination.list_sessions(workspace=self.slug, active_only=True),
                         "the impostor's session was created anyway")
        self.assertTrue(events.read_events(workspace=self.slug,
                                           event_type=board.OWNERSHIP_EVENT),
                        "an ownership refusal must leave an audit trail")

        # (3) Honestly seated, a handoff to a name that was never declared is refused.
        os.environ["BRAIN_AGENT"] = "opencode"
        session = self._lease(files="src/auth.py")
        with self.assertRaises(TopologyError) as ctx:
            coordination.end(session["id"], summary="probe", workspace=self.slug,
                             target_agent="eve")
        self.assertIn("not a declared seat", str(ctx.exception))

    @unittest.expectedFailure
    def test_p1_an_unseated_caller_may_not_pick_any_identity(self):
        """p1 — OPEN (needs a signed seat token): with no `BRAIN_AGENT` the flag is
        still believed.

        `cli._agent` documents this as accepted ("an empty $BRAIN_AGENT means the caller
        is not running under a seat at all, so the flag stands — and is recorded as
        unverified"). Measured here: it stands *and nothing* records it, so the simplest
        way to forge any seat is to declare none. The probe accepts either refusal or a
        verifiable trail; a signed seat token will turn it green, at which point the
        decorator comes off rather than the assertion getting weaker.
        """
        h.run("-w", self.slug, "post", "impostor note", "--agent", "codex", expect=None)
        attributed = [note["agent"] for note in coordination.read_notes(workspace=self.slug)]
        self.assertIn(attributed, ([], ["unknown"]),
                      "an unproven identity was written to the board as fact: "
                      f"{attributed}")


# =============================================================================
# attack 2 — write into another agent's inbox, bypassing messaging
# =============================================================================


class TestP2InboxForgery(HostileCase):
    """p2 defends attack 2: `BRAIN_AGENT=opencode brain post --to agy --agent codex`
    used to succeed, and `agy` read the message as one from `codex`.

    No topology is declared here on purpose: in a workspace with no policy the *only*
    thing that can stop this forgery is the seat binding, so the probe cannot pass for
    the wrong reason (a routing denial would mask an unbound sender).
    """

    def test_p2_sender_must_match_the_seat(self):
        """p2 — BLOCKED at both edges: a sender that contradicts `BRAIN_AGENT` never
        reaches the victim's inbox — and the honestly-seated message still does."""
        os.environ["BRAIN_AGENT"] = "opencode"

        # Edge 1: the CLI, which is how the attack was first demonstrated.
        code, out, err = h.run("-w", self.slug, "post", "forged dispatch",
                               "--to", "agy", "--agent", "codex", expect=None)
        self.assertNotEqual(0, code, f"the inbox forgery succeeded: {out!r}")

        # Edge 2: the python API, skipping the CLI entirely. An agent that imports
        # `brain` is inside the trust domain, so this is the edge that actually matters.
        with self.assertRaises(BrainError) as ctx:
            messaging.send(body="api forgery", sender="codex", recipient="agy",
                           workspace=self.slug)
        self.assertIn("codex", str(ctx.exception))

        forged = [m for m in messaging.read_inbox("agy", self.slug)
                  if m["from"] == "codex"]
        self.assertEqual(forged, [], f"agy received a message it should not have: {forged}")
        outbox = ws_mod.workspace_dir(self.slug) / const.MESSAGES_DIR / "outbox-codex"
        self.assertFalse(list(outbox.glob("*.md")),
                         "the impersonated seat got an outbox record for work it never did")

        # The product still works: seated send is delivered and correctly attributed.
        code, out, err = h.run("-w", self.slug, "post", "honest dispatch",
                               "--to", "agy", "--agent", "opencode", expect=None)
        self.assertEqual(0, code, f"refusal leaked into the honest path: {err}")
        delivered = [(m["from"], m["body"]) for m in messaging.read_inbox("agy", self.slug)]
        self.assertEqual([("opencode", "honest dispatch")], delivered)


# =============================================================================
# attack 3 — edit topology.yaml to grant yourself an edge
# =============================================================================


class TestP3SelfGrantedEdge(HostileCase):
    """p3 defends attack 3: rewrite the pinned routing policy and take the edge.

    Defence: the witness's signed pin records the digest of `topology.yaml`; a file that
    no longer hashes to it is drifted, `load()` raises, and every consumer of the graph
    (routing, `brain topology`) fails closed.
    """

    def test_p3_editing_a_pinned_topology_denies_the_new_edge(self):
        """p3 — BLOCKED: rewrite the pinned policy for an edge and every consumer fails
        closed on the digest drift."""
        # The approved policy: a DAG, no `hermes` seat anywhere in it.
        path = self._topology({"codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]},
                               "agy": {"edges": []}})
        self._pin_topology(path)
        self.assertEqual("pinned", topology.pin_status(self.slug)[0])
        allowed, why = topology.can_route("codex", "agy", workspace=self.slug)
        self.assertTrue(allowed, why)
        allowed, why = topology.can_route("codex", "hermes", workspace=self.slug)
        self.assertFalse(allowed, "the seat must not be routable before the edit")
        self.assertIn("not a declared seat", why)

        # The attack: give yourself a route to a seat the approved policy never listed.
        path.write_text(yaml.safe_dump({"version": "1", "seats": {
            "codex": {"edges": [{"kind": "delegates_to", "to": "agy"},
                                {"kind": "delegates_to", "to": "hermes"}]},
            "agy": {"edges": []}, "hermes": {"edges": []}}}, sort_keys=False),
            encoding="utf-8")

        state, detail = topology.pin_status(self.slug)
        self.assertEqual("drifted", state, detail)
        self.assertIn("edited after it was pinned", detail)
        with self.assertRaises(TopologyError) as ctx:
            topology.load(self.slug)
        self.assertIn("not the policy that was approved", str(ctx.exception))
        with self.assertRaises(TopologyError):
            topology.can_route("codex", "hermes", workspace=self.slug)
        # The CLI fails closed too, rather than rendering the attacker's graph.
        code, out, err = h.run("-w", self.slug, "topology", expect=None)
        self.assertNotEqual(0, code, f"brain topology served an unpinned graph: {out!r}")


# =============================================================================
# attack 4 — BRAIN_BYPASS=1 as a universal key
# =============================================================================


class TestP4BypassAsUniversalKey(HostileCase):
    """p4 defends attack 4: any process at uid 1000 can set `BRAIN_BYPASS=1`.

    Defence today: with no trust root there is nothing to verify a human-minted grant
    against, so a bypass needs *either* a grant the privileged witness minted (impossible
    for an agent) *or* the legacy env var — and the legacy path is audited as
    `BYPASS_SELF_GRANTED`, which is what removes the "silent universal key" property. The
    root-owned install (an unreadable `/etc/second-brain/attest.fpr`) is what turns this
    from "logged" into "refused"; until then the honest verdict is DETECTED-LABELLED.
    """

    def test_p4_bypass_without_a_grant_is_refused(self):
        """p4 — BLOCKED: nothing presented, and nothing self-typed, opens the gate."""
        self.assertFalse(attest.installed(), "probe assumes the bootstrap trust root")
        ok, why = grants.bypass(seat="codex", action="route:codex->agy", workspace=self.slug)
        self.assertFalse(ok, f"nothing was presented, yet bypass said yes: {why}")
        self.assertIn("BRAIN_BYPASS", why)
        self.assertFalse(paths.bypass_enabled(spend=False, seat="codex",
                                             action="route:codex->agy",
                                             workspace=self.slug))
        # A token an agent typed by itself is not a grant either.
        os.environ["BRAIN_BYPASS_GRANT"] = "deadbeef" + "." + "cafebabe"
        ok, why = grants.bypass(seat="codex", action="route:codex->agy", workspace=self.slug)
        self.assertFalse(ok, f"a self-minted grant token bought a bypass: {why}")

        # And the gate the attacker wanted stays shut.
        self._topology({"codex": {"edges": []}, "agy": {"edges": []}})
        allowed, why = topology.can_route("codex", "agy", workspace=self.slug)
        self.assertFalse(allowed, why)
        self.assertIn("no routing edge", why)
        self.assertEqual([], events.read_events(workspace=self.slug,
                                                event_type="BYPASS_SELF_GRANTED"))

    def test_p4_self_granted_bypass_is_audited(self):
        """p4 — DETECTED-LABELLED: `BRAIN_BYPASS=1` still works in bootstrap, but it must
        not work quietly: the event stream says the caller authorised itself."""
        self._topology({"codex": {"edges": []}, "agy": {"edges": []}})
        os.environ["BRAIN_BYPASS"] = "1"

        allowed, why = topology.can_route("codex", "agy", workspace=self.slug)
        self.assertTrue(allowed, f"bootstrap break-glass stopped working: {why}")
        self.assertIn("granted override", why)

        events_a = events.read_events(workspace=self.slug, event_type="BYPASS_SELF_GRANTED")
        self.assertEqual(1, len(events_a),
                         "a bypass walked over the boundary without being audited")
        payload = events_a[0]["payload"]
        self.assertEqual("codex", payload.get("seat"))
        self.assertEqual("route:codex->agy", payload.get("action"))
        self.assertIn("no trust root", str(payload.get("detail")))
        self.assertEqual("AUTHORIZE", events_a[0]["stage"])


# =============================================================================
# attack 5 — self-mark a card done with no evidence
# =============================================================================


class TestP5DoneWithoutEvidence(HostileCase):
    """p5 defends attack 5: an agent moves its own card to `done` and walks away."""

    def test_p5_done_without_any_evidence_is_refused(self):
        """p5 — BLOCKED: `done` with nothing behind it raises ReviewGate."""
        with self.assertRaises(ReviewGate) as ctx:
            board.move(self.task["id"], "done", workspace=self.slug)
        self.assertIn("cannot reach [done]", str(ctx.exception))

    def test_p5_done_on_a_claimed_test_result_is_refused(self):
        """p5 — BLOCKED: satisfy the review gate with words, then ask for done."""
        session = self._lease()
        self._handoff(session["id"])
        self._clean_tree()
        self.assertEqual([], evidence.get_receipts(self.task["id"], self.slug))

        with self.assertRaises(UnverifiedEvidenceError) as ctx:
            board.move(self.task["id"], "done", workspace=self.slug)
        message = str(ctx.exception)
        self.assertIn("without OS execution receipt", message,
                      "wrong reason — this probe proves the *evidence* gate")
        self.assertNotIn("outside session lease", message)


# =============================================================================
# attack 6 — manufacture a passing receipt from an asserted exit code
# =============================================================================


class TestP6AssertedExitCode(HostileCase):
    """p6 defends attack 6: `brain record-evidence --exit-code 0` used to write a
    receipt that opened the completion gate. It is now a tripwire."""

    def test_p6_asserting_an_exit_code_raises_and_is_audited(self):
        """p6 — BLOCKED: typing your own exit code raises, is audited, and yields no
        receipt the completion gate could be opened with."""
        session = self._lease()
        self._handoff(session["id"])
        self._clean_tree()

        code, out, err = h.run("-w", self.slug, "record-evidence", "--task", self.task["id"],
                               "--cmd-text", "pytest -q", "--exit-code", "0",
                               "--session", session["id"], expect=None)
        self.assertNotEqual(0, code, "the engine accepted a typed-in exit code")
        self.assertIn("REFUSED", err)

        refusals = events.read_events(workspace=self.slug,
                                       event_type="EVIDENCE_FORGERY_REFUSED")
        self.assertEqual(1, len(refusals), "the attempt was not written to the audit stream")
        self.assertEqual("0", str(refusals[0]["payload"].get("claimed_exit_code")))
        self.assertEqual(self.task["id"], refusals[0]["task_id"])

        # Nothing usable was produced: no receipt on file, so the gate still refuses.
        self.assertEqual([], evidence.get_receipts(self.task["id"], self.slug))
        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertFalse(ok, detail)
        self.assertIn("no execution receipt", detail)
        with self.assertRaises(UnverifiedEvidenceError):
            board.move(self.task["id"], "done", workspace=self.slug)


# =============================================================================
# attack 7 — tamper with a sealed receipt
# =============================================================================


class TestP7ReceiptTampering(HostileCase):
    """p7 defends attack 7: edit a sealed receipt on disk and keep the signature.

    Two halves, both measured on this host:
      * naive tamper (flip the bytes, leave the signature) — BLOCKED by verification;
      * tamper *and re-sign with the vault's own key* — ALLOWED, because the trust root
        here is `bootstrap`: there is no root-owned `/etc/second-brain/attest.fpr`, so
        `attest.sign()` succeeds in a process running as uid 1000. That is the accepted
        risk the root install removes, and the second test pins the label
        (`trust_mode: bootstrap`) that makes it visible to a reviewer instead of
        pretending the boundary already holds.
    """

    def _failing_receipt(self):
        session = self._lease()
        self._handoff(session["id"], test_status="pytest: 12 passed in 0.4s")
        receipt = evidence.record_receipt(task_id=self.task["id"], command="pytest -q",
                                          exit_code=1, stderr="AssertionError: 1 != 0",
                                          workspace=self.slug, session_id=session["id"])
        self._clean_tree()
        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertFalse(ok, detail)
        self.assertIn("failed with exit code 1", detail)
        path = evidence.receipts_dir(self.slug) / f"{receipt['receipt_id']}.json"
        return receipt, path

    def test_p7_hand_edited_receipt_fails_attestation(self):
        """p7 — BLOCKED: flip `exit_code` in a sealed receipt and keep the signature."""
        receipt, path = self._failing_receipt()
        tampered = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, tampered["exit_code"])
        tampered["exit_code"] = 0
        tampered["verified"] = True
        path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")

        loaded = evidence.load_receipt(path)
        self.assertEqual(attest.FORGED, loaded["_attestation"])

        # Surfaced and labelled, not dropped: deleting evidence must not be an option.
        listed = evidence.get_receipts(self.task["id"], self.slug)
        self.assertEqual(1, len(listed), "the tampered receipt vanished from the record")
        self.assertEqual([attest.FORGED], [r["_attestation"] for r in listed])

        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertFalse(ok, "a hand-edited receipt opened the completion gate")
        self.assertIn("failed attestation", detail)
        self.assertNotIn("outside session lease", detail)

        with self.assertRaises(UnverifiedEvidenceError) as ctx:
            board.move(self.task["id"], "done", workspace=self.slug)
        self.assertIn("failed attestation", str(ctx.exception))

    def test_p7_resigning_with_the_vault_key_is_allowed_and_labelled(self):
        """p7 — DETECTED-LABELLED: tamper *and* re-sign with the vault key is accepted.

        This is not a pass for the boundary, it is the boundary's own label. Once
        `/etc/second-brain/attest.fpr` exists and the key is root-owned mode 0600,
        `attest.sign()` raises PermissionError for uid 1000 and this probe must be
        rewritten to assert the refusal.
        """
        receipt, path = self._failing_receipt()
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["exit_code"] = 0
        tampered.pop(attest.ATTEST_FIELD, None)

        self.assertEqual("bootstrap", attest.mode())
        path.write_text(json.dumps(attest.sign(tampered), indent=2), encoding="utf-8")

        listed = evidence.get_receipts(self.task["id"], self.slug)
        self.assertEqual([attest.VERIFIED], [r["_attestation"] for r in listed])
        self.assertEqual(["bootstrap"], [r["_trust_mode"] for r in listed],
                         "a bootstrap-signed receipt must not masquerade as installed")

        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertTrue(ok, f"bootstrap re-signing was blocked: {detail}")
        self.assertIn("[bootstrap trust]", detail,
                      "the verdict must name the trust level it was reached under")


# =============================================================================
# attack 8 — tamper with the transcript after sealing
# =============================================================================


class TestP8TranscriptTampering(HostileCase):
    """p8 defends attack 8: run a real test, then quietly rewrite the transcript it
    left behind. The signed hash is recomputed at verification time, so the edit has to
    be caught even though the receipt itself is still a valid signature."""

    def test_p8_one_extra_byte_in_a_sealed_transcript_is_refused(self):
        """p8 — BLOCKED: append one byte to a sealed transcript and the signed-vs-now
        hash pair is named in the refusal."""
        session = self._lease()
        receipt = evidence.run_test(task_id=self.task["id"],
                                    command="python3 -c \"print('12 passed in 0.4s')\"",
                                    workspace=self.slug, session_id=session["id"])
        self._handoff(session["id"])
        self.assertEqual(0, receipt["exit_code"], "the honest run must actually pass")
        self._clean_tree()

        transcript = Path(receipt["transcript_path"])
        signed_hash = receipt["transcript_sha256"]
        self.assertTrue(signed_hash, "run_test sealed no transcript hash — probe is vacuous")
        intact, why = evidence.transcript_intact(receipt)
        self.assertTrue(intact, why)
        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertTrue(ok, detail)

        # The attack: one byte, appended after sealing.
        with open(transcript, "ab") as sink:
            sink.write(b"x")
        now_hash = hashlib.sha256(transcript.read_bytes()).hexdigest()
        self.assertNotEqual(signed_hash, now_hash)

        reloaded = evidence.load_receipt(evidence.receipts_dir(self.slug)
                                         / f"{receipt['receipt_id']}.json")
        intact, why = evidence.transcript_intact(reloaded)
        self.assertFalse(intact, "an edited transcript still read as intact")
        self.assertIn("modified after the receipt was sealed", why)
        self.assertIn(signed_hash[:12], why, "the signed hash must be named in the refusal")
        self.assertIn(now_hash[:12], why, "the actual hash must be named in the refusal")

        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertFalse(ok, "a doctored transcript opened the completion gate")
        self.assertIn("modified after the receipt was sealed", detail)
        self.assertNotIn("outside session lease", detail)
        with self.assertRaises(UnverifiedEvidenceError) as ctx:
            board.move(self.task["id"], "done", workspace=self.slug)
        self.assertIn("modified after the receipt was sealed", str(ctx.exception))


# =============================================================================
# attack 9 — race / double-claim
# =============================================================================


class TestP9DoubleClaim(HostileCase):
    """p9 defends attack 9: two live sessions on overlapping files, and a seat that
    moves a card it does not own.

    Enforced today: the second lease loses the race (`LeaseConflict`, audited as
    `LEASE_DENIED`); a foreign seat cannot take a card whose lease is still live, cannot
    claim credit on a `review`/`done` move, and — since the ownership rule was derived
    from the sessions that produced the work — cannot retarget a card whose builder has
    already closed its session.
    """

    def test_p9_second_lease_on_the_same_file_is_refused(self):
        """p9 — BLOCKED: two live sessions cannot both hold the same file, and the
        loser must not end up holding the lease."""
        holder = self._lease(files="src/shared.py")
        code, out, err = h.run("-w", self.slug, "start", "--agent", "claude",
                               "--task-id", self.task["id"], "--files", "src/shared.py",
                               expect=None)
        self.assertNotEqual(0, code, f"the double claim won the race: {out!r}")
        self.assertIn("REFUSED", err)

        with self.assertRaises(LeaseConflict) as ctx:
            coordination.start(agent="claude", workspace=self.slug,
                               task_id=self.task["id"], files="src/shared.py")
        self.assertEqual("opencode", ctx.exception.holder)

        active = coordination.list_sessions(workspace=self.slug, active_only=True)
        self.assertEqual([holder["id"]], [s["id"] for s in active],
                         "the contested session was created anyway")
        conflicts = coordination.check_files(["src/shared.py"], workspace=self.slug)
        self.assertEqual("opencode", conflicts[0][1]["agent"],
                         "the loser's attempt stole the lease")
        self.assertEqual(2, len(events.read_events(workspace=self.slug,
                                                   event_type="LEASE_DENIED")))

    def test_p9_a_seat_cannot_move_another_seats_card(self):
        """p9 — BLOCKED: a foreign seat may not move, or re-author, another seat's card.

        The card is the interesting case because its builder's session has already
        ended: no live lease is left to protect it, and the handoff went to `agy`, not to
        `gemini`. Refusing here means ownership is derived from the sessions that did the
        work rather than from the `--agent` the caller types.
        """
        session = self._lease(files="src/auth.py")
        with self._as("opencode"):
            coordination.end(session["id"], summary="done", workspace=self.slug,
                             target_agent="agy", test_status="pytest: 12 passed")
        _, card = board.get_task(self.task["id"], self.slug)
        self.assertEqual("review", str(card["fm"].get("status")))
        self.assertEqual("opencode", str(card["fm"].get("agent")))

        os.environ["BRAIN_AGENT"] = "gemini"
        code, out, err = h.run("-w", self.slug, "move", self.task["id"],
                               "--status", "blocked", "--agent", "gemini",
                               "--notes", "mine now", expect=None)
        self.assertNotEqual(0, code, f"a foreign seat moved a card it does not own: {out!r}")
        _, stolen = board.get_task(self.task["id"], self.slug)
        self.assertEqual("review", str(stolen["fm"].get("status")))
        self.assertEqual("opencode", str(stolen["fm"].get("agent")),
                         "the attacker rewrote the card's authorship")


# =============================================================================
# attack 10 — escape the registered workspace filesystem
# =============================================================================


class TestP10WorkspaceEscape(HostileCase):
    """p10 defends attack 10: do the damage outside the registered workspace root, or
    point the integrity check somewhere else, and still collect the credit.

    Enforced today: a lease naming paths outside the workspace buys no coverage; a `cwd`
    outside the workspace root is refused rather than believed; and a `cwd` inside the
    workspace but below the git root no longer picks the tree at all — the workspace
    registration does. What stays open is confinement itself: nothing *stops* a run from
    happening outside the root, so the probe below pins the strongest true statement — the
    receipt names the real directory, so the escape is visible to a reviewer.
    """

    def _dirty_workspace_with_a_lying_lease(self):
        """A real unleased code change inside the workspace, plus a clean-looking
        receipt so that only the tree gate stands between the attacker and `done`."""
        self._repo(self.root)
        (self.root / "rogue_change.py").write_text("import os\n", encoding="utf-8")
        session = self._lease(files="src/auth.py")
        self._handoff(session["id"])
        evidence.record_receipt(task_id=self.task["id"], command="pytest -q", exit_code=0,
                                stdout="12 passed", workspace=self.slug,
                                session_id=session["id"])
        return session

    def test_p10_lease_paths_outside_the_workspace_buy_no_coverage(self):
        """p10 — BLOCKED: a lease naming paths outside the workspace root clears nothing
        that an honest lease would not."""
        self._dirty_workspace_with_a_lying_lease()

        foreign = ["../../etc/passwd", "/etc/shadow", "../outside/secret.py",
                   str(self.root.parent.parent / "elsewhere.py")]
        clean, outside = evidence.check_working_tree(self.slug, leased_files=foreign)
        self.assertFalse(clean, "an out-of-workspace lease laundered a real change")
        self.assertIn("rogue_change.py", outside)

        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertFalse(ok, detail)
        self.assertIn("working tree contains changes outside session lease", detail)

    def test_p10_a_caller_supplied_cwd_must_not_blind_the_gate(self):
        """p10 — BLOCKED: a `cwd` outside the registered workspace root is refused, not
        believed.

        Pointing the integrity check at another directory — a freshly `git init`-ed empty
        one — used to hide a change sitting inside the registered workspace. The
        workspace registration now decides what the tree is, so the breach is reported.
        """
        self._dirty_workspace_with_a_lying_lease()
        decoy = self._repo(h._TMP / "clean-decoy-repo")

        clean, outside = evidence.check_working_tree(self.slug, leased_files=[],
                                                     cwd=str(decoy))
        self.assertFalse(clean, f"the decoy tree was accepted: {outside}")
        self.assertIn(f"is outside workspace '{self.slug}'", outside[0])

        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug,
                                          cwd=str(decoy))
        self.assertFalse(ok, f"cwd override hid the unleased change: {detail}")
        self.assertIn("working tree contains changes outside session lease", detail)
        self.assertIn(f"is outside workspace '{self.slug}'", detail)

    def test_p10_a_cwd_below_the_repo_root_is_judged_against_the_workspace(self):
        """p10 — BLOCKED: a `cwd` inside the workspace but *below* the git root no longer
        disables the tree check.

        `check_working_tree` used to judge only a directory containing `.git`, so any
        subdirectory of the real repository resolved to "not a repo" and was reported
        clean, and the receipt alone then opened the gate. The workspace registration now
        picks the tree — a caller-supplied `cwd` never does — so the unleased change is
        still reported from any directory under the root.
        """
        self._dirty_workspace_with_a_lying_lease()
        below_root = self.root / "src"
        below_root.mkdir(parents=True, exist_ok=True)

        clean, outside = evidence.check_working_tree(self.slug, leased_files=[],
                                                     cwd=str(below_root))
        self.assertFalse(clean, f"a subdirectory cwd silenced the tree check: {outside}")
        self.assertIn("rogue_change.py", outside)

        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug,
                                          cwd=str(below_root))
        self.assertFalse(ok, f"a subdirectory cwd laundered the receipt: {detail}")
        self.assertIn("working tree contains changes outside session lease", detail)

    def test_p10_a_cwd_naming_the_workspace_root_is_judged_and_not_penalised(self):
        """p10 — BLOCKED: naming the root itself as `cwd` is an honest run, not an escape.

        The same hardening that refuses a `cwd` outside the root must not turn the
        honest spelling — the one a test runner in the project directory actually uses —
        into a refusal, and it must not switch the tree check off either: judged from the
        root, the unleased change is still reported, and an honest lease of that file
        still clears the gate.
        """
        self._dirty_workspace_with_a_lying_lease()

        clean, outside = evidence.check_working_tree(self.slug, leased_files=[],
                                                     cwd=str(self.root))
        self.assertFalse(clean, f"a cwd equal to the root disabled the tree check: {outside}")
        self.assertIn("rogue_change.py", outside)
        self.assertNotIn(f"is outside workspace '{self.slug}'", outside[0],
                         "the honest cwd was refused by name instead of judged")

        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug,
                                          cwd=str(self.root))
        self.assertFalse(ok, detail)
        self.assertIn("working tree contains changes outside session lease", detail)
        self.assertNotIn("is outside workspace", detail)

        honest = ["rogue_change.py"]
        clean, outside = evidence.check_working_tree(self.slug, leased_files=honest,
                                                     cwd=str(self.root))
        self.assertTrue(clean, f"an honest lease was not believed from the root: {outside}")
        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug,
                                          leased_files=honest, cwd=str(self.root))
        self.assertTrue(ok, f"an honest run was penalised by its own cwd: {detail}")

    def test_p10_a_lease_naming_a_directory_covers_the_files_under_it(self):
        """p10 — BLOCKED: a lease is a prefix, so a directory lease covers what is inside
        it and nothing else.

        Sessions record directories (`src`, not every path under it) all the time, so the
        prefix rule is what keeps honest work moving; it is also the rule an attacker
        would want stretched. Asserted for the spellings `_normalise` exists to absorb
        (`pkg`, `pkg/`, `./pkg`) and against a second, unleased change that the directory
        lease must not launder.
        """
        self._dirty_workspace_with_a_lying_lease()
        pkg = self.root / "pkg"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "keep.py").write_text("VERSION = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "pkg/keep.py"], cwd=str(self.root), check=True,
                       capture_output=True, text=True)
        (pkg / "keep.py").write_text("VERSION = 2\n", encoding="utf-8")

        baseline, outside = evidence.check_working_tree(self.slug, leased_files=[])
        self.assertFalse(baseline, "the tree gate is not judging this repo at all")
        self.assertIn("pkg/keep.py", outside,
                      f"the nested change was never reported — probe is vacuous: {outside}")
        self.assertIn("rogue_change.py", outside)

        for spelling in ("pkg", "pkg/", "./pkg"):
            clean, outside = evidence.check_working_tree(self.slug, leased_files=[spelling])
            self.assertNotIn("pkg/keep.py", outside,
                             f"lease {spelling!r} did not cover pkg/keep.py: {outside}")
            self.assertIn("rogue_change.py", outside,
                          f"lease {spelling!r} reached outside itself: {outside}")

        # Leasing the directory *and* every other path the gate reports does clear it: the
        # prefix rule is satisfiable, not a refusal that can never be paid off.
        clean, outside = evidence.check_working_tree(
            self.slug, leased_files=["pkg"] + [f for f in outside if f != "pkg/keep.py"])
        self.assertTrue(clean, f"an honest lease was not believed: {outside}")

        # The directory lease stops at the directory: the unleased change beside it stands.
        clean, outside = evidence.check_working_tree(self.slug, leased_files=["pkg"])
        self.assertFalse(clean, "a directory lease laundered the whole workspace")
        self.assertIn("rogue_change.py", outside)
        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug,
                                          leased_files=["pkg"])
        self.assertFalse(ok, f"a directory lease opened the gate over an unleased file: {detail}")
        self.assertIn("rogue_change.py", detail)

    def test_p10_a_run_outside_the_workspace_is_recorded_not_refused(self):
        """p10 — DETECTED-LABELLED: nothing confines a run outside the workspace root,
        but the receipt says where it happened, so a reviewer can see it.

        The tree gate cannot be fooled from that position either
        (`test_p10_a_cwd_below_the_repo_root_is_judged_against_the_workspace`); what stays
        open is that a run may *happen* somewhere the workspace never registered.
        """
        elsewhere = self.root.parent / f"{self.slug}-outside"
        elsewhere.mkdir(parents=True, exist_ok=True)
        session = self._lease()
        receipt = evidence.run_test(task_id=self.task["id"],
                                    command="python3 -c \"print('out of workspace')\"",
                                    cwd=str(elsewhere), workspace=self.slug,
                                    session_id=session["id"])
        self.assertEqual(str(elsewhere), str(Path(receipt["cwd"]).resolve()),
                         "the receipt must record the real cwd, not the registered root")
        self.assertEqual(0, receipt["exit_code"], receipt.get("output_snippet"))
        self.assertFalse(Path(receipt["cwd"]).resolve().is_relative_to(self.root),
                         "the run escaped the workspace root — confinement is the open gap")
        self.assertEqual(attest.VERIFIED, receipt["_attestation"])
        self.assertEqual("bootstrap", receipt["_trust_mode"])


# =============================================================================
# bonus — the honest path still works
# =============================================================================


class TestP11HonestPath(HostileCase):
    """p11 is the anti-regression: every gate above must still open for real work.

    A tier that only ever says "refused" measures nothing; if a hardening change breaks
    this probe, the security it bought was bought from the product.
    """

    def test_p11_a_real_passing_run_opens_the_gate(self):
        """p11 — WORKS: an honest `brain test` receipt still carries a card to `done`."""
        os.environ["BRAIN_AGENT"] = "opencode"
        session = self._lease()
        code, out, err = h.run("-w", self.slug, "test", "--task", self.task["id"],
                               "--session", session["id"],
                               "--cmd-text", "python3 -c \"print('14 passed in 0.42s')\"",
                               expect=None)
        self.assertEqual(0, code, f"brain test failed: {out}{err}")

        listed = evidence.get_receipts(self.task["id"], self.slug)
        self.assertEqual(1, len(listed))
        receipt = listed[0]
        self.assertEqual(0, receipt["exit_code"])
        self.assertEqual(attest.VERIFIED, receipt["_attestation"],
                         "an honest run must produce a verified receipt")
        self.assertEqual("bootstrap", receipt["_trust_mode"],
                         "the receipt must admit which trust root signed it")

        self._handoff(session["id"], test_status="python3: 14 passed")
        self._clean_tree()
        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertTrue(ok, detail)

        result = board.move(self.task["id"], "done", workspace=self.slug)
        self.assertEqual("done", result["status"])
        self.assertTrue(result["changed"])
        self.assertIn("verified execution receipt", result["detail"])
        self.assertEqual(1, len(events.read_events(workspace=self.slug,
                                                   event_type="TASK_COMPLETED",
                                                   task_id=self.task["id"])))


# =============================================================================
# attack 12 — speak as another session's seat at the evidence gate; spend a grant
# =============================================================================


class TestP12ReceiptAttribution(HostileCase):
    """p12 defends one half of attack 12: a receipt is a statement about a *session*, so
    filing it under somebody else's session is an identity forgery, not bookkeeping.

    `session_id` used to be free text on the way into `record_receipt`: seat `agy` could
    attach its own passing run to `opencode`'s session and have the completion gate read
    it as that session's witnessed work, with `agy` nowhere in the record. The defence is
    `evidence._claim_session`, which refuses a session whose `agent` is not the calling
    seat and audits the attempt. Its *other* rule — a session may not speak for a card it
    is not working — is written but never reached, which the second probe below keeps
    visible.
    """

    def test_p12_a_seat_may_not_file_evidence_under_another_seats_session(self):
        """p12 — BLOCKED: `agy` files a passing receipt under `opencode`'s session."""
        session = self._lease(files="src/auth.py")
        self._handoff(session["id"])
        self._clean_tree()
        self.assertEqual([], evidence.get_receipts(self.task["id"], self.slug))

        with self._as("agy"):
            with self.assertRaises(BrainError) as ctx:
                evidence.record_receipt(task_id=self.task["id"], command="pytest -q",
                                        exit_code=0, stdout="12 passed in 0.4s",
                                        workspace=self.slug, session_id=session["id"])
        message = str(ctx.exception)
        self.assertIn("belongs to opencode, not agy", message)
        self.assertIn("session you hold", message)

        # Nothing usable survived the attempt: no receipt on file, so the gate stays shut.
        self.assertEqual([], evidence.get_receipts(self.task["id"], self.slug),
                         "the refused receipt was written anyway")
        refusals = events.read_events(workspace=self.slug,
                                       event_type="EVIDENCE_ATTRIBUTION_REFUSED")
        self.assertEqual(1, len(refusals), "the attempt was not written to the audit stream")
        self.assertEqual(session["id"], refusals[0]["payload"].get("session"))
        self.assertEqual("opencode", refusals[0]["payload"].get("holder"))
        ok, detail = evidence.verify_task(self.task["id"], workspace=self.slug)
        self.assertFalse(ok, detail)
        self.assertIn("no execution receipt", detail)

        # The honest path: a seat filing under the session it holds still gets evidence.
        with self._as("opencode"):
            receipt = evidence.record_receipt(task_id=self.task["id"], command="pytest -q",
                                              exit_code=0, stdout="12 passed in 0.4s",
                                              workspace=self.slug, session_id=session["id"])
        self.assertEqual(attest.VERIFIED, receipt["_attestation"])
        self.assertEqual(session["id"], receipt["session_id"])
        listed = evidence.get_receipts(self.task["id"], self.slug)
        self.assertEqual([receipt["receipt_id"]], [r["receipt_id"] for r in listed])
        self.assertEqual(1, len(events.read_events(workspace=self.slug,
                                                   event_type="EVIDENCE_ATTRIBUTION_REFUSED")),
                         "the honest filing must not be counted as another attempt")

    def test_p12_a_receipt_may_not_be_attached_to_a_card_the_session_never_worked_on(self):
        """p12 — BLOCKED: a run from an unrelated card is not evidence here.

        The second half of the attribution rule: a session whose `task_id` is set may not
        speak for another card. It existed in `_claim_session` but could not fire from any
        caller, because `record_receipt` passed the session and the workspace while holding
        on to the `task_id` it had just been handed — so the receipt landed and
        `verify_task(card_b)` reported "verified execution receipt … (exit code 0)" for a
        card that was never run. The gate that caught it was then a *different* one
        (`board.move`: "no finished session is linked to this task"), which is the shape of
        this bug: the evidence layer mis-stating what it has, and the completion gate
        cleaning up after it.
        """
        session = self._lease(files="src/auth.py")
        card_b = board.create_task("Unrelated card", workspace=self.slug,
                                   agent="opencode", status="running")
        found = coordination.get(session["id"], self.slug)
        self.assertEqual(self.task["id"], found[1]["fm"].get("task_id"),
                         "the session records no card, so the probe would be vacuous")
        self._handoff(session["id"])
        self._clean_tree()

        with self._as("opencode"):
            with self.assertRaises(BrainError) as ctx:
                evidence.record_receipt(task_id=card_b["id"], command="pytest -q",
                                        exit_code=0, stdout="12 passed in 0.4s",
                                        workspace=self.slug, session_id=session["id"])
        self.assertIn(f"is working {self.task['id']}, not {card_b['id']}", str(ctx.exception))
        self.assertEqual([], evidence.get_receipts(card_b["id"], self.slug),
                         "the cross-card receipt was written anyway")
        self.assertEqual(1, len(events.read_events(workspace=self.slug,
                                                   event_type="EVIDENCE_ATTRIBUTION_REFUSED")))
        ok, detail = evidence.verify_task(card_b["id"], workspace=self.slug)
        self.assertFalse(ok, f"another card's run opened this one's gate: {detail}")


class TestP12BypassGrant(HostileCase):
    """p12 defends the other half of attack 12: the bypass grant is the *only* thing that
    opens a gate once trust is installed, so it has to be spendable, seat-bound,
    signature-bound, time-bound and single-use — all five, at once.

    Four of those were broken together by the plumbing: `find()` parked a `_path` key
    inside the signed record, which made `attest.verify` report `forged` for every
    genuine grant, and `bypass()` shadowed its own `spend` boolean against the module
    function of the same name, so the first gate reached after install died with
    `TypeError: 'bool' object is not callable`. A grant nobody can spend is not a
    vulnerability — but it is the failure that pushes an operator to re-enable
    `BRAIN_BYPASS=1`, which is. These probes run the real `check`/`consume`/`_retire`
    over a real record in `grants/`, with only the trust root simulated.
    """

    def _mint_grant(self, seat="agy", minutes=30, expires: str = ""):
        """Write the record `brain-witness grant-bypass` writes and return
        (record, token), the token being exactly what the witness prints: `<sig>.<nonce>`.

        Minting one takes a password by design, so the probe cannot ask for it; the
        spending side is what is under test, and it reads an ordinary file from
        `grants/` — signed here with the vault's bootstrap key so the real `attest.verify`
        can be pointed at it too.
        """
        nonce = os.urandom(16).hex()
        stamp = datetime.now(timezone.utc)
        record = {
            "kind": "bypass-grant",
            "grant_id": f"grant_{nonce[:12]}",
            "nonce": nonce,
            "seat": seat,
            "reason": "probe: the operator authorised exactly this one step",
            "issued": _iso(stamp),
            "expires": expires or _iso(stamp + timedelta(minutes=minutes)),
            "authorised_by_uid": 0,
            "single_use": True,
        }
        grants.grants_dir().mkdir(parents=True, exist_ok=True)
        signed = attest.seal_to_file(grants.grants_dir() / f"{record['grant_id']}.json",
                                     record)
        return signed, signed[attest.ATTEST_FIELD]["sig"] + "." + nonce

    def test_p12_a_genuine_grant_is_spendable_by_the_seat_it_names(self):
        """p12 — WORKS: a real grant verifies, opens the gate once, and for its seat only.

        The first block runs with **no** mocks: `check()` never asks whether trust is
        installed, so this is the genuine signature path that `find()`'s injected `_path`
        used to poison. The spend itself needs the install simulated.
        """
        record, token = self._mint_grant(seat="agy")
        nonce = record["nonce"]

        found, path = grants.find(nonce)
        self.assertIsNotNone(found, "a live grant was not found on record")
        self.assertEqual(record["grant_id"], Path(path).stem)
        self.assertNotIn("_path", found,
                         "bookkeeping was parked inside the signed record")
        self.assertEqual(attest.VERIFIED, attest.verify(found),
                         "a genuine grant read as forged — no gate in the machine can open")
        ok, why = grants.check(seat="agy", raw_token=token)
        self.assertTrue(ok, f"a genuine grant did not check out: {why}")

        os.environ[grants.TOKEN_ENV] = token
        with self._installed_trust():
            # Bound to the seat it was minted for: a stranger gets nothing, and — because
            # the refusal happens before the record is retired — it burns nothing either.
            ok, why = grants.bypass(seat="codex", action="route:codex->agy",
                                    workspace=self.slug)
            self.assertFalse(ok, f"a grant bound to agy opened a gate for codex: {why}")
            self.assertIn("bound to seat 'agy'", why)
            self.assertIsNotNone(grants.find(nonce)[0],
                                 "a rejected attempt spent somebody else's grant")

            # The holder, through the gate every caller uses. This is the call that used to
            # raise TypeError before `spend` stopped shadowing `spend()`.
            ok, why = grants.bypass(seat="agy", action="route:codex->agy",
                                    workspace=self.slug)
            self.assertTrue(ok, f"a live grant could not be spent: {why}")
            self.assertIn(record["grant_id"], why)

    def test_p12_a_spent_grant_cannot_be_spent_twice(self):
        """p12 — BLOCKED: replay the token the witness printed and get nothing."""
        record, token = self._mint_grant(seat="agy")
        nonce, grant_id = record["nonce"], record["grant_id"]
        os.environ[grants.TOKEN_ENV] = token

        with self._installed_trust():
            ok, why = grants.bypass(seat="agy", action="route:agy->codex",
                                    workspace=self.slug)
            self.assertTrue(ok, f"the first spend failed, so replay is unmeasured: {why}")
            # Out of the live set — into `grants/used/`, which is the point of `single_use`
            # surviving a root-owned directory.
            self.assertIsNone(grants.find(nonce)[1], "the spent record is still live")
            self.assertEqual([], grants.list_grants())
            used = grants.grants_dir() / "used" / f"{grant_id}.json"
            self.assertTrue(used.is_file(),
                            "a spent grant must be retired, not deleted: "
                            f"{sorted(p.name for p in (grants.grants_dir() / 'used').glob('*'))}")
            self.assertFalse((grants.grants_dir() / f"{grant_id}.json").exists())

            os.environ[grants.TOKEN_ENV] = token
            ok, why = grants.bypass(seat="agy", action="route:agy->codex",
                                    workspace=self.slug)
        self.assertFalse(ok, "a spent grant bought a second bypass")
        self.assertIn("already spent", why)
        self.assertEqual(1, len(events.read_events(workspace=self.slug,
                                                   event_type="BYPASS_GRANTED")),
                         "the replay must not be audited as a second authorisation")
        self.assertEqual(1, len(events.read_events(workspace=self.slug,
                                                   event_type="BYPASS_DENIED")))

    def test_p12_a_token_carrying_no_signature_presents_no_grant(self):
        """p12 — BLOCKED: hand over the nonce without the signature.

        The nonce is not secret — it is the grant's filename, and the record is 0644 for
        the seat to read — so a gate that accepted a bare nonce would let anyone holding a
        *copy* of a live-or-spent file walk over the line. The signature is the half that
        proves the witness wrote it. Both spellings of "no signature" are refused, each by
        its own named reason: a token that is not even in `<sig>.<nonce>` form is not
        recognised as a grant at all, and one that is in the form with the signature
        stripped is refused as carrying nothing.
        """
        record, token = self._mint_grant(seat="agy")
        sig, _, nonce = token.rpartition(".")
        for presented, reason in ((nonce, "no grant token in $BRAIN_BYPASS_GRANT"),
                                  ("." + nonce, "carries no signature")):
            with self.subTest(token=presented):
                os.environ[grants.TOKEN_ENV] = presented
                with self._installed_trust():
                    ok, why = grants.bypass(seat="agy", action="route:agy->codex",
                                            workspace=self.slug)
                    self.assertFalse(ok, f"{presented!r} was accepted as a grant: {why}")
                    self.assertIn(reason, why)
                    # Refused without spending: the holder still has what it was given.
                    self.assertIsNotNone(grants.find(nonce)[1])
                    self.assertEqual([], events.read_events(workspace=self.slug,
                                                            event_type="BYPASS_GRANTED"))

        os.environ[grants.TOKEN_ENV] = token
        self.assertEqual(sig, record[attest.ATTEST_FIELD]["sig"],
                         "the probe's own token drifted from the record on disk")
        with self._installed_trust():
            ok, why = grants.bypass(seat="agy", action="route:agy->codex",
                                    workspace=self.slug)
        self.assertTrue(ok, f"the same grant presented in full was refused: {why}")

    def test_p12_an_expired_grant_buys_nothing(self):
        """p12 — BLOCKED: the authorisation outlived the emergency it authorised."""
        gone = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        for stamp in (gone, "the day before the audit"):
            with self.subTest(expires=stamp):
                _record, token = self._mint_grant(seat="agy", expires=stamp)
                os.environ[grants.TOKEN_ENV] = token
                with self._installed_trust():
                    ok, why = grants.bypass(seat="agy", action="route:agy->codex",
                                            workspace=self.slug)
                self.assertFalse(ok, f"an expired grant (expires={stamp!r}) was honoured: {why}")
                self.assertIn("expired", why)
                self.assertTrue(grants.list_grants(),
                                "a grant that cannot be honoured must not be retired either")
        self.assertEqual([], events.read_events(workspace=self.slug,
                                                event_type="BYPASS_GRANTED"))


# =============================================================================
# attack 13 — defeat the privileged authority file, not the code that reads it
# =============================================================================


WITNESS_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "brain-witness.py"


def _load_witness():
    """Import the privileged witness as a module.

    It is a standalone script that lives outside the vault precisely so nothing in here
    can *be* it, and it imports nothing from `brain`, so loading it by path is cheap and
    runs no command: `main()` is behind a `__name__` guard.
    """
    spec = importlib.util.spec_from_file_location("brain_witness", str(WITNESS_SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestP13WitnessAllowList(HostileCase):
    """p13 defends attack 13: the witness's allow-list is the only thing between an agent
    at uid 1000 and a root-signed "test passed" receipt, so it has to mean *this program*.

    Matching argv[0] on its basename made `/tmp/anything/pytest` the allow-listed runner —
    a passwordless signing oracle for a script the attacker wrote. `permitted()` now
    resolves both sides the way the child will (through the witness's own `FIXED_PATH`,
    not the caller's `$PATH`) and requires the same realpath; and `cmd_exec` refuses any
    command carrying a flag that exits 0 without exercising anything, which would otherwise
    be a free receipt for a test that never ran.
    """

    def _witness(self, allowed=("python3 -m unittest", "pytest")):
        """The witness, with its two globals pointed at throwaway files.

        `ALLOWED_FILE` and `FIXED_PATH` are module globals under `/etc/second-brain`,
        which this probe cannot write, so they are set on the imported module object. The
        attacker's directory is deliberately *not* on `FIXED_PATH` — that is the real
        shape of this attack, since the child's PATH is the witness's own constant: the
        caller reaches the look-alike by naming its path, and `shutil.which` honours a
        path containing a separator.
        """
        witness = _load_witness()
        home = h._TMP / f"witness-{uuid.uuid4().hex[:6]}"
        trusted, attacker = home / "trusted-bin", home / "attacker-bin"
        trusted.mkdir(parents=True, exist_ok=True)
        attacker.mkdir(parents=True, exist_ok=True)
        real, shim = trusted / "pytest", attacker / "pytest"
        real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        shim.write_text("#!/bin/sh\necho '12 passed in 0.4s'\nexit 0\n", encoding="utf-8")
        for path in (real, shim):
            path.chmod(0o755)
        listing = home / "allowed-commands"
        listing.write_text("".join(f"{line}\n" for line in allowed), encoding="utf-8")
        witness.ALLOWED_FILE = str(listing)
        witness.FIXED_PATH = f"{trusted}:/usr/local/sbin:/usr/local/bin:/usr/bin"
        # Vacuity guards: the refusals below only mean something if the programs they
        # imitate resolve to real executables on this witness's PATH.
        self.assertTrue(witness._executable("pytest"))
        self.assertTrue(witness._executable("python3"))
        return witness, shim, real

    def _refusal(self, witness, argv) -> str:
        """Run `cmd_exec` and hand back why it died. Everything probed here is refused
        before the witness reaches for root, a vault allow-list or a subprocess, so no
        command is run and nothing is signed."""
        sink = io.StringIO()
        with contextlib.redirect_stderr(sink):
            with self.assertRaises(SystemExit) as ctx:
                witness.cmd_exec(argv)
        self.assertEqual(2, ctx.exception.code, sink.getvalue())
        return sink.getvalue()

    def test_p13_a_look_alike_executable_is_not_the_allow_listed_one(self):
        """p13 — BLOCKED: `/tmp/…/attacker-bin/pytest` is not `pytest`."""
        witness, shim, real = self._witness()

        self.assertTrue(witness.permitted(["pytest", "-q"]),
                        "the allow-listed runner stopped working — the refusal below is vacuous")
        self.assertTrue(witness.permitted([str(real), "-q"]),
                        "naming the allow-listed program by absolute path is the same program")
        self.assertFalse(witness.permitted([str(shim), "-q"]),
                         "a look-alike basename was accepted as the allow-listed runner")
        self.assertTrue(os.access(str(shim), os.X_OK) and shim.is_file(),
                        "the shim was refused because it is not runnable, not because it "
                        "is somebody else's program")
        self.assertNotEqual(os.path.realpath(str(shim)), os.path.realpath(str(real)))
        self.assertEqual("pytest", shim.name)
        # A name the list carries but no file resolves to, and an empty argv.
        self.assertFalse(witness.permitted([str(h._TMP / "nowhere" / "pytest"), "-q"]))
        self.assertFalse(witness.permitted([]))
        self.assertFalse(witness.permitted(["pytest-not", "-q"]))

    def test_p13_an_allow_listed_program_name_is_not_the_whole_program(self):
        """p13 — BLOCKED: `python3` on the list is not a licence to run any python program.

        Each allow-list line is a token *prefix*; without that the list is one line —
        `python3` — and the witness signs `python3 -c "print(1)"` as a passing test.
        """
        witness, _, _ = self._witness()
        self.assertTrue(witness.permitted(["python3", "-m", "unittest"]))
        self.assertTrue(witness.permitted(["python3", "-m", "unittest", "discover",
                                           "-s", "tests"]))
        self.assertFalse(witness.permitted(["python3"]),
                         "the bare interpreter is not an allow-listed command")
        self.assertFalse(witness.permitted(["python3", "-c", "print(1)"]),
                         "an inline program was accepted on the strength of its interpreter")
        self.assertFalse(witness.permitted(["python3", "-m", "pytest", "-q"]))

    def test_p13_a_flag_that_exits_zero_without_running_anything_is_not_evidence(self):
        """p13 — BLOCKED: `python3 -m unittest --help` exits 0 having proved nothing."""
        witness, _, _ = self._witness()
        for flag in witness.NO_EVIDENCE:
            with self.subTest(flag=flag):
                command = ["python3", "-m", "unittest", flag]
                self.assertTrue(witness.permitted(command),
                                "the allow-list alone would sign this — it is the "
                                "no-evidence rule that has to refuse it")
                detail = self._refusal(witness, ["--task", "t1", "--workspace", "hostile",
                                                 "--cwd", str(h._TMP), "--", *command])
                self.assertIn("is not evidence", detail)
        # The same command without such a flag gets past this gate (and is stopped later,
        # by the checks this probe is not about).
        detail = self._refusal(witness, ["--task", "t1", "--workspace", "hostile",
                                         "--cwd", str(h._TMP), "--",
                                         "python3", "-m", "unittest"])
        self.assertNotIn("is not evidence", detail)


class TestP13TopologyPinDeletion(HostileCase):
    """p13 defends the other half of attack 13: the signed pin is what makes
    `topology.yaml` somebody else's decision, so *deleting* the pin must be as useless as
    editing the file.

    `load()` used to raise only on `drifted`, which made `rm meta/topology.pin.json` the
    cheap way back to an agent-written policy — no digest to beat, just an `unlink` in a
    directory the agent owns. The asymmetry is the contract: with no trust root installed
    an unpinned topology still loads, because that is the only way the machine is usable
    before the operator shows up.
    """

    def _approved_graph(self) -> Path:
        """The policy a human approved: `codex -> agy`, and no `hermes` seat anywhere."""
        return self._topology({"codex": {"role": "planner",
                                         "edges": [{"kind": "delegates_to", "to": "agy"}]},
                               "agy": {"role": "reviewer", "edges": []}})

    def _attacker_graph(self, path: Path) -> Path:
        """The same file rewritten to grant a route the approved policy never listed."""
        path.write_text(yaml.safe_dump({"version": "1", "seats": {
            "codex": {"edges": [{"kind": "delegates_to", "to": "agy"},
                                {"kind": "delegates_to", "to": "hermes"}]},
            "agy": {"edges": []}, "hermes": {"edges": []}}}, sort_keys=False),
            encoding="utf-8")
        return path

    def test_p13_deleting_the_pin_does_not_unpin_the_policy(self):
        """p13 — BLOCKED: edit the pinned graph and you are caught; delete the pin and
        the graph stops being policy too."""
        path = self._approved_graph()
        pin = self._pin_topology(path)

        with self._installed_trust():
            self.assertEqual("pinned", topology.pin_status(self.slug)[0])
            self.assertIsNotNone(topology.load(self.slug),
                                 "an untouched pinned topology must load — or every refusal "
                                 "below is just the gate being broken")
            allowed, why = topology.can_route("codex", "agy", workspace=self.slug)
            self.assertTrue(allowed, why)

        # Step 1, the attack p3 already measures under bootstrap trust.
        self._attacker_graph(path)
        with self._installed_trust():
            state, detail = topology.pin_status(self.slug)
            self.assertEqual("drifted", state, detail)
            self.assertIn("edited after it was pinned", detail)
            with self.assertRaises(TopologyError) as ctx:
                topology.can_route("codex", "hermes", workspace=self.slug)
            self.assertIn("not the policy that was approved", str(ctx.exception))

        # Step 2: take the pin away and the caught edit is policy again — unless the
        # absence of a pin is itself fatal once trust is installed.
        self.assertTrue(pin.is_file())
        pin.unlink()
        with self._installed_trust():
            state, detail = topology.pin_status(self.slug)
            self.assertEqual("unpinned", state, detail)
            with self.assertRaises(TopologyError) as ctx:
                topology.load(self.slug)
            message = str(ctx.exception)
            self.assertIn("no approved pin", message)
            self.assertIn("Deleting the pin is not an un-pin", message)
            with self.assertRaises(TopologyError) as ctx:
                topology.can_route("codex", "hermes", workspace=self.slug)
            self.assertIn("no approved pin", str(ctx.exception),
                          "can_route served the attacker's graph instead of denying it")
            code, out, err = h.run("-w", self.slug, "topology", expect=None)
            self.assertNotEqual(0, code,
                                f"brain topology rendered an un-pinned graph: {out!r}")

    def test_p13_bootstrap_still_loads_an_unpinned_topology(self):
        """p13 — WORKS: before the install there is no witness to have pinned anything,
        so the unpinned graph must still route.

        The refusal above is conditioned on `attest.installed()`; if that condition is ever
        dropped, this probe goes red and the machine is bricked for every workspace that
        has not been through an operator it cannot reach.
        """
        path = self._attacker_graph(self._approved_graph())
        self.assertFalse(attest.installed(), "this probe needs the bootstrap trust root")
        self.assertEqual("unpinned", topology.pin_status(self.slug)[0])
        self.assertIsNotNone(topology.load(self.slug),
                             "an unpinned topology stopped loading in bootstrap mode")
        allowed, why = topology.can_route("codex", "hermes", workspace=self.slug)
        self.assertTrue(allowed, f"bootstrap routing was refused on a missing pin: {why}")
        self.assertIn("edge: codex --delegates_to--> hermes", why)
        code, out, err = h.run("-w", self.slug, "topology", expect=None)
        self.assertEqual(0, code, f"brain topology failed on an unpinned file: {err}")


if __name__ == "__main__":
    unittest.main()
