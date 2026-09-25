#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy entry point for the Mission Control API.

The implementation moved to `brain.http` (threading server, real telemetry, workspace
scoping, refusals surfaced as HTTP 409, universal `/agent/bootstrap`). This file keeps
`python server.py` and the npm scripts working.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain import http  # noqa: E402
from brain.paths import stdout_utf8  # noqa: E402

if __name__ == "__main__":
    stdout_utf8()
    sys.exit(http.main())
