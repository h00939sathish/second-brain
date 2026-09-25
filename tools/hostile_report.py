#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the adversarial tier and report per-probe verdicts as JSON.

`brain verify-boundary` is the consumer. Parsing `unittest -v` text was the obvious
first attempt and it is wrong: verbose output appends the verdict to the test's
docstring line, so a probe's result lands under a sentence instead of its own name.
Asking the TestResult for the buckets is exact.
"""

import json
import os
import re
import sys
import unittest

PROBE = re.compile(r"_p(\d+)")


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def probe_of(test_id: str) -> str:
    found = PROBE.search(test_id.lower())
    return f"p{found.group(1)}" if found else test_id.rsplit(".", 1)[-1]


def main(argv: list) -> int:
    vault = argv[1] if len(argv) > 1 else os.getcwd()
    os.chdir(vault)
    sys.path.insert(0, vault)
    suite = unittest.TestLoader().discover("tests/hostile", top_level_dir=".")
    tests = list(flatten(suite))
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(suite)

    def ids(items):
        return [(t.id() if hasattr(t, "id") else t[0].id()) for t in items]

    failed, errored = ids(result.failures), ids(result.errors)
    known_open = ids(result.expectedFailures)
    skipped = ids(result.skipped)
    unexpected = ids(result.unexpectedSuccesses)
    accounted = set(failed) | set(errored) | set(known_open) | set(skipped)
    passed = [t.id() for t in tests if t.id() not in accounted]

    verdicts = {}
    for test_id in passed:
        verdicts.setdefault(probe_of(test_id), {"blocked": [], "open": [], "broken": [],
                                                "skipped": []})["blocked"].append(test_id)
    for bucket, group in (("open", known_open), ("broken", failed + errored),
                          ("skipped", skipped)):
        for test_id in group:
            verdicts.setdefault(probe_of(test_id), {"blocked": [], "open": [], "broken": [],
                                                    "skipped": []})[bucket].append(test_id)

    # A probe is blocked only if every one of its probes closed: one broken assertion
    # on a defence is the same answer as the defence not being there.
    tally = {name: ("broken" if v["broken"] else "open" if v["open"]
                    else "skipped" if v["skipped"] else "blocked")
             for name, v in verdicts.items()}
    report = {
        "probes": len(tally),
        "blocked": sum(1 for s in tally.values() if s == "blocked"),
        "known_open": sum(1 for s in tally.values() if s == "open"),
        "broken": sum(1 for s in tally.values() if s == "broken"),
        "skipped": sum(1 for s in tally.values() if s == "skipped"),
        "verdicts": tally,
        "detail": verdicts,
        "unexpected_successes": unexpected,
        "suite_ok": result.wasSuccessful(),
        "ran": result.testsRun,
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if result.wasSuccessful() and not unexpected else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
