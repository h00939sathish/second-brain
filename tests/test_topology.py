# -*- coding: utf-8 -*-
"""Tests for enforced agent topology graph."""

import hashlib
import json
import os
import unittest
import yaml

import tests.harness as h
from brain import board, const, coordination, dispatch, store, topology
from brain.errors import TopologyError


class TestTopology(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("topo")
        from brain import workspaces as ws_mod
        self.ws_root = ws_mod.workspace_dir(self.slug)
        self.topo_file = self.ws_root / const.META_DIR / "topology.yaml"

    def _write_topology(self, data: dict):
        self.topo_file.parent.mkdir(parents=True, exist_ok=True)
        self.topo_file.write_text(yaml.safe_dump(data), encoding="utf-8")

    def test_missing_topology_is_ungoverned_not_secretly_permissive(self):
        self.assertFalse(self.topo_file.exists())
        self.assertIsNone(topology.load(self.slug))
        allowed, reason = topology.can_route("codex", "opencode", workspace=self.slug)
        self.assertTrue(allowed)
        self.assertIn("ungoverned", reason)

    def test_valid_topology_loads_and_lists_seats(self):
        sample = {
            "version": "1",
            "seats": {
                "codex": {
                    "role": "planner",
                    "edges": [{"kind": "delegates_to", "to": "opencode"}]
                },
                "opencode": {
                    "role": "builder",
                    "edges": [{"kind": "delegates_to", "to": "agy"}]
                },
                "agy": {
                    "role": "reviewer",
                    "edges": [{"kind": "can_observe", "to": "opencode"}]
                }
            }
        }
        self._write_topology(sample)
        loaded = topology.load(self.slug)
        self.assertIsNotNone(loaded)
        self.assertIn("codex", loaded["seats"])

        seats = topology.list_seats(self.slug)
        self.assertEqual(len(seats), 3)

        # Rendering
        ascii_graph = topology.render_ascii(self.slug)
        self.assertIn("Agent Topology", ascii_graph)
        self.assertIn("[codex]", ascii_graph)

    def test_cycle_detection_in_delegates_to(self):
        cycle_sample = {
            "version": "1",
            "seats": {
                "a": {"edges": [{"kind": "delegates_to", "to": "b"}]},
                "b": {"edges": [{"kind": "delegates_to", "to": "c"}]},
                "c": {"edges": [{"kind": "delegates_to", "to": "a"}]},
            }
        }
        self._write_topology(cycle_sample)
        with self.assertRaises(TopologyError) as ctx:
            topology.load(self.slug)
        self.assertIn("delegation cycle detected", str(ctx.exception))

    def test_enforce_routing_allows_declared_edge(self):
        sample = {
            "version": "1",
            "seats": {
                "codex": {
                    "role": "planner",
                    "edges": [{"kind": "delegates_to", "to": "opencode"}]
                },
                "opencode": {
                    "role": "builder",
                    "edges": [{"kind": "delegates_to", "to": "agy"}]
                },
                "agy": {
                    "role": "reviewer",
                    "edges": []
                }
            }
        }
        self._write_topology(sample)

        # codex -> opencode is allowed
        allowed, reason = topology.can_route("codex", "opencode", workspace=self.slug)
        self.assertTrue(allowed)
        self.assertIn("delegates_to", reason)

        # codex -> agy is NOT allowed (no edge)
        allowed, reason = topology.can_route("codex", "agy", workspace=self.slug)
        self.assertFalse(allowed)
        self.assertIn("no routing edge", reason)

    def test_bypass_overrides_topology_restriction(self):
        sample = {
            "version": "1",
            "seats": {
                "codex": {"edges": []},
                "agy": {"edges": []}
            }
        }
        self._write_topology(sample)
        allowed, _ = topology.can_route("codex", "agy", workspace=self.slug)
        self.assertFalse(allowed)

        os.environ["BRAIN_BYPASS"] = "1"
        try:
            allowed, reason = topology.can_route("codex", "agy", workspace=self.slug)
            self.assertTrue(allowed)
            self.assertIn("granted override", reason)
        finally:
            os.environ.pop("BRAIN_BYPASS", None)

    def test_undeclared_source_is_denied(self):
        """A name that is not a seat gets no route: identity cannot be improvised."""
        self._write_topology({"version": "1", "seats": {
            "codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]}, "agy": {"edges": []}}})
        allowed, reason = topology.can_route("eve", "agy", workspace=self.slug)
        self.assertFalse(allowed)
        self.assertIn("not declared", reason)

    def test_anonymous_source_is_denied(self):
        self._write_topology({"version": "1", "seats": {
            "codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]}, "agy": {"edges": []}}})
        allowed, reason = topology.can_route("", "agy", workspace=self.slug)
        self.assertFalse(allowed)
        self.assertIn("no source agent", reason)

    def test_self_routing_requires_a_declared_edge(self):
        self._write_topology({"version": "1", "seats": {
            "codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]}, "agy": {"edges": []}}})
        allowed, _ = topology.can_route("codex", "codex", workspace=self.slug)
        self.assertFalse(allowed)

    def test_topology_edited_after_its_pin_raises(self):
        """The graph an agent rewrote is not the policy that was approved."""
        from brain import attest
        self._write_topology({"version": "1", "seats": {
            "codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]},
            "agy": {"edges": [{"kind": "delegates_to", "to": "codex"}]}}})
        digest = hashlib.sha256(self.topo_file.read_bytes()).hexdigest()
        pin = self.topo_file.parent / "topology.pin.json"
        pin.write_text(json.dumps(attest.sign({
            "kind": "topology-pin", "workspace": self.slug, "sha256": digest,
            "timestamp": "2026-01-01T00:00:00Z"}), indent=2), encoding="utf-8")
        self.assertEqual("pinned", topology.pin_status(self.slug)[0])

        self._write_topology({"version": "1", "seats": {
            "codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]},
            "agy": {"edges": [{"kind": "delegates_to", "to": "codex"},
                              {"kind": "delegates_to", "to": "eve"}]}}})
        self.assertEqual("drifted", topology.pin_status(self.slug)[0])
        with self.assertRaises(TopologyError):
            topology.load(self.slug)

    def test_coordination_end_enforces_handoff_topology(self):
        sample = {
            "version": "1",
            "seats": {
                "opencode": {"edges": [{"kind": "delegates_to", "to": "agy"}]},
                "agy": {"edges": []},
                "codex": {"edges": []},
            }
        }
        self._write_topology(sample)
        session = coordination.start(agent="opencode", workspace=self.slug, task="coding")

        # Handoff to agy is allowed by topology
        coordination.end(session["id"], summary="done", target_agent="agy", workspace=self.slug)

        # New session trying invalid handoff to codex
        session2 = coordination.start(agent="opencode", workspace=self.slug, task="coding 2")
        with self.assertRaises(TopologyError):
            coordination.end(session2["id"], summary="done", target_agent="codex", workspace=self.slug)

    def test_cli_topology_commands(self):
        sample = {
            "version": "1",
            "seats": {
                "codex": {"role": "planner", "edges": [{"kind": "delegates_to", "to": "opencode"}]},
                "opencode": {"role": "builder", "edges": []}
            }
        }
        self._write_topology(sample)
        code, out, _ = h.run("-w", self.slug, "topology")
        self.assertEqual(code, 0)
        self.assertIn("Agent Topology", out)

        code, out, _ = h.run("-w", self.slug, "topology", "validate")
        self.assertEqual(code, 0)
        self.assertIn("is valid", out)
