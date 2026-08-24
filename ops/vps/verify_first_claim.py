#!/usr/bin/env python3
"""Verify exactly-once technical evidence for the first resumed inbound."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def verify(audit: dict[str, Any]) -> dict[str, Any]:
    commit_count = audit.get("commit_count")
    one_commit = (
        commit_count == 1
        if commit_count is not None
        else audit.get("inbound_count") == 1
        and audit.get("commit_state") == "completed"
    )
    checks = {
        "one_inbound": audit.get("inbound_count") == 1,
        "one_decision": audit.get("decision_count") == 1,
        "one_proof": audit.get("proof_count") == 1,
        "one_valid_proof": audit.get("valid_proof_count") == 1,
        # The production audit function exposes the single canonical inbound's
        # embedded conversation_commit state rather than a separate count.
        "one_commit": one_commit,
        "commit_completed": audit.get("commit_state") == "completed",
        "at_most_one_outbound": isinstance(audit.get("outbound_count"), int)
        and 0 <= audit["outbound_count"] <= 1,
        "outbound_released_after_proof": (
            audit.get("outbound_count") == 0
            or audit.get("outbound_released_after_proof") is True
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "inbound_id": audit.get("inbound_id"),
        "outbound_status": audit.get("outbound_status"),
        "ledger_revision": audit.get("ledger_revision"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbound-id", required=True)
    args = parser.parse_args()
    try:
        audit = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid audit JSON: {exc}") from exc
    if not isinstance(audit, dict):
        raise SystemExit("audit payload must be an object")
    if str(audit.get("inbound_id") or "") != args.inbound_id:
        raise SystemExit("audit inbound identity mismatch")
    result = verify(audit)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["passed"]:
        failed = ",".join(
            name for name, passed in result["checks"].items() if not passed
        )
        raise SystemExit(f"first claim verification failed: {failed}")


if __name__ == "__main__":
    main()
