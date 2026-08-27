#!/usr/bin/env python3
"""Persist and verify the continuous production environment evidence."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--disk-percent", type=int, required=True)
    collect.add_argument("--disk-limit", type=int, required=True)
    collect.add_argument("--unsafe-table-grants", type=int, required=True)
    collect.add_argument("--unsafe-function-grants", type=int, required=True)
    collect.add_argument("--tables-without-rls", type=int, required=True)
    collect.add_argument("--backup-ok", choices=("true", "false"), required=True)
    collect.add_argument("--backup-detail", default="")
    collect.add_argument("--restore-ok", choices=("true", "false"), required=True)
    collect.add_argument("--restore-detail", default="")
    verify = sub.add_parser("verify")
    verify.add_argument("--input", type=Path, required=True)
    verify.add_argument("--max-age-hours", type=float, default=26)
    verify.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if args.command == "collect":
        gates = {
            "disk": {"ok": args.disk_percent < args.disk_limit, "percent": args.disk_percent, "limit": args.disk_limit},
            "data_api_grants": {"ok": args.unsafe_table_grants == 0 and args.unsafe_function_grants == 0, "unsafe_tables": args.unsafe_table_grants, "unsafe_functions": args.unsafe_function_grants},
            "rls": {"ok": args.tables_without_rls == 0, "tables_without_rls": args.tables_without_rls},
            "scheduled_backup": {"ok": args.backup_ok == "true", "detail": args.backup_detail},
            "restore_test": {"ok": args.restore_ok == "true", "detail": args.restore_detail},
        }
        payload = {
            "schema_version": 1,
            "kind": "production_environment_evidence",
            "collected_at": now().isoformat().replace("+00:00", "Z"),
            "ok": all(gate["ok"] for gate in gates.values()),
            "gates": gates,
        }
        atomic_write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        raise SystemExit(0 if payload["ok"] else 1)

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        age_hours = (now() - parse_time(str(payload["collected_at"]))).total_seconds() / 3600
        gates_ok = bool(payload.get("ok"))
        fresh = 0 <= age_hours <= args.max_age_hours
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        raise SystemExit(1 if args.strict else 0)
    result = {"ok": gates_ok and fresh, "fresh": fresh, "age_hours": round(age_hours, 2), "gates_ok": gates_ok}
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["ok"] or not args.strict else 1)


if __name__ == "__main__":
    main()
