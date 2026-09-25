# -*- coding: utf-8 -*-
"""Constitutional invariant verification engine for the Local Agent Control Plane."""

import subprocess
import sys

from .paths import VAULT

INVARIANT_CATALOG = (
    ("INV-001", "Active Uncontested File Lease", "tests.invariants.test_inv001_leases"),
    ("INV-002", "Machine-Verified Evidence for Completion", "tests.invariants.test_inv002_completion"),
    ("INV-003", "Dependency-Satisfied Execution (Task DAG)", "tests.invariants.test_inv003_dependencies"),
    ("INV-004", "Temporal Knowledge Validity (Git Anchoring)", "tests.invariants.test_inv004_claims"),
    ("INV-005", "Canonical Append-Only Event Logging", "tests.invariants.test_inv005_events"),
    ("INV-006", "Untrusted Proposal Boundary", "tests.invariants.test_inv006_authority"),
    ("INV-007", "Validated State Machine Transitions", "tests.invariants.test_inv007_state_machine"),
    ("INV-008", "Deliberation Gate for High-Risk Execution", "tests.invariants.test_inv008_deliberation"),
)


def verify_all() -> dict:
    """Run test suites for all 7 constitutional invariants in isolated environments."""
    results = []
    total_passed = 0

    for inv_id, title, test_module in INVARIANT_CATALOG:
        res = subprocess.run(
            [sys.executable, "-m", "unittest", test_module],
            cwd=str(VAULT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        passed = res.returncode == 0
        if passed:
            total_passed += 1

        count = 0
        for line in res.stderr.splitlines():
            if line.startswith("Ran ") and " test" in line:
                try:
                    count = int(line.split()[1])
                except (ValueError, IndexError):
                    pass

        results.append({
            "id": inv_id,
            "title": title,
            "status": "PASS" if passed else "FAIL",
            "passed": passed,
            "test_count": count,
            "detail": "" if passed else (res.stderr.strip() or res.stdout.strip()),
        })

    return {
        "invariants": results,
        "total": len(INVARIANT_CATALOG),
        "passed": total_passed,
        "all_passed": total_passed == len(INVARIANT_CATALOG),
    }
