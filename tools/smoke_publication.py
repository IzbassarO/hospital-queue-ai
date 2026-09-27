#!/usr/bin/env python3
"""One line about the active operational publication, from the JSON of /operational-intelligence/overview on stdin.

Used by `make smoke` so the recipe stays readable; needs nothing but the standard library.
"""

import json
import sys

snapshot = json.load(sys.stdin)["snapshot"]
print(
    f"  publication   {snapshot['publication_id']} "
    f"({snapshot['signal_count']} signals, {snapshot['forecast_count']} forecast rows, "
    f"identity {snapshot['publication_identity_sha256'][:12]}…)"
)
