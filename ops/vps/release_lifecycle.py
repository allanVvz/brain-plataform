#!/usr/bin/env python3
"""Durable, atomic production release lifecycle state.

The state lives under ``.deploy`` so installing a new release artifact does not
erase it.  This intentionally uses the host filesystem instead of introducing
another production table: deploy orchestration must remain available even when
Postgres is the component being migrated or recovered.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = (
    "prepared",
    "images_pulled",
    "claims_paused",
    "queue_drained",
    "migration_complete",
    "candidate_healthy",
    "validator_complete",
    "soak_complete",
    "awaiting_resume_authorization",
    "workers_resumed",
    "verified",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _state_dir() -> Path:
    return Path(os.environ.get("DEPLOY_STATE_DIR") or _root() / ".deploy")


def _state_path() -> Path:
    return _state_dir() / "lifecycle.json"


def _event_path() -> Path:
    return _state_dir() / "lifecycle-events.ndjson"


def _release_archive_path(candidate_sha: str) -> Path:
    return _state_dir() / "releases" / f"{candidate_sha}.json"


def _claims_marker_path() -> Path:
    return _state_dir() / "control" / "claims-paused.json"


def _write_claims_marker(value: dict[str, Any]) -> None:
    """Publish a root-owned marker that the unprivileged worker can read."""
    path = _claims_marker_path()
    _atomic_write(path, value)
    # The worker mounts only this directory read-only and runs as UID 10001.
    # Keep lifecycle state private, but make this non-secret control contract
    # traversable/readable without granting the container write access.
    os.chmod(path.parent, 0o755)
    os.chmod(path, 0o644)


def _validate_sha(value: str, label: str) -> str:
    candidate = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(candidate):
        raise SystemExit(f"{label} must be a full lowercase Git SHA")
    return candidate


def _read() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        raise SystemExit(f"release lifecycle is not prepared: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid release lifecycle state: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("release lifecycle state must be a JSON object")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _append_event(state: dict[str, Any], event: str, detail: dict[str, Any]) -> None:
    payload = {
        "at": _now(),
        "event": event,
        "candidate_sha": state.get("candidate_sha"),
        "stage": state.get("stage"),
        **detail,
    }
    path = _event_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def _parse_gates(values: list[str]) -> dict[str, Any]:
    gates: dict[str, Any] = {}
    for item in values:
        key, separator, raw = item.partition("=")
        if not separator or not key.strip():
            raise SystemExit(f"gate must use key=value: {item}")
        normalized: Any = raw.strip()
        if normalized.lower() in {"true", "false"}:
            normalized = normalized.lower() == "true"
        elif normalized.isdigit():
            normalized = int(normalized)
        gates[key.strip()] = normalized
    return gates


def _save(state: dict[str, Any], event: str, detail: dict[str, Any] | None = None) -> None:
    state["updated_at"] = _now()
    _atomic_write(_state_path(), state)
    _append_event(state, event, detail or {})


def _cmd_prepare(args: argparse.Namespace) -> None:
    candidate = _validate_sha(args.candidate_sha, "candidate SHA")
    previous = _validate_sha(args.previous_sha, "previous SHA")
    existing: dict[str, Any] | None = None
    if _state_path().exists():
        existing = _read()
    if existing and existing.get("candidate_sha") == candidate:
        print(json.dumps(existing, ensure_ascii=False, sort_keys=True))
        return
    if existing and existing.get("stage") != "verified" and not args.force:
        raise SystemExit(
            "another release lifecycle is unfinished; resume it or use --force after review"
        )
    if existing and existing.get("stage") != "verified" and args.force:
        reason = str(args.force_reason or "").strip()
        if not reason:
            raise SystemExit("forced lifecycle supersession requires --force-reason")
        archived = dict(existing)
        archived["superseded_at"] = _now()
        archived["superseded_by"] = candidate
        archived["supersede_reason"] = reason
        archived_candidate = _validate_sha(
            str(archived.get("candidate_sha") or ""), "archived candidate SHA"
        )
        _atomic_write(_release_archive_path(archived_candidate), archived)
        _append_event(
            existing,
            "superseded",
            {"superseded_by": candidate, "reason": reason},
        )
    now = _now()
    state: dict[str, Any] = {
        "schema_version": 1,
        "candidate_sha": candidate,
        "previous_sha": previous,
        "impact_class": args.impact_class,
        "stage": "prepared",
        "stage_entered_at": now,
        "created_at": now,
        "updated_at": now,
        "pause_reason": args.pause_reason or None,
        "expected_workers": sorted(set(args.expected_worker or ["workers"])),
        "pending_messages": max(0, args.pending_messages),
        "gates": {},
        "resume_authorization": None,
        "history": [{"stage": "prepared", "at": now}],
    }
    _save(state, "prepared", {"impact_class": args.impact_class})
    print(json.dumps(state, ensure_ascii=False, sort_keys=True))


def _cmd_advance(args: argparse.Namespace) -> None:
    state = _read()
    current = str(state.get("stage") or "")
    target = args.stage
    if current not in STAGES or target not in STAGES:
        raise SystemExit("unknown release lifecycle stage")
    current_index = STAGES.index(current)
    target_index = STAGES.index(target)
    safety_regression = args.safety_pause and target == "claims_paused"
    if target_index < current_index and not safety_regression:
        raise SystemExit(f"cannot regress lifecycle from {current} to {target}")
    if target != current:
        entered = _now()
        state["stage"] = target
        state["stage_entered_at"] = entered
        state.setdefault("history", []).append({"stage": target, "at": entered})
    if args.reason:
        state["pause_reason"] = args.reason
    if args.pending_messages is not None:
        state["pending_messages"] = max(0, args.pending_messages)
    state.setdefault("gates", {}).update(_parse_gates(args.gate or []))
    _save(
        state,
        "safety_claims_paused" if safety_regression else "stage_advanced",
        {"from": current, "to": target},
    )
    print(json.dumps(state, ensure_ascii=False, sort_keys=True))


def _cmd_authorize(args: argparse.Namespace) -> None:
    state = _read()
    if state.get("stage") != "awaiting_resume_authorization":
        raise SystemExit(
            "resume authorization is accepted only at awaiting_resume_authorization"
        )
    actor = str(args.actor or "").strip()
    reason = str(args.reason or "").strip()
    if not actor or not reason:
        raise SystemExit("resume authorization requires actor and reason")
    state["resume_authorization"] = {
        "authorized": True,
        "actor": actor,
        "reason": reason,
        "at": _now(),
    }
    _save(state, "resume_authorized", {"actor": actor})
    print(json.dumps(state["resume_authorization"], ensure_ascii=False, sort_keys=True))


def _cmd_gate(args: argparse.Namespace) -> None:
    state = _read()
    updates = _parse_gates(args.gate)
    state.setdefault("gates", {}).update(updates)
    _save(state, "gates_recorded", {"keys": sorted(updates)})
    print(json.dumps(updates, ensure_ascii=False, sort_keys=True))


def _cmd_pause_claims(args: argparse.Namespace) -> None:
    state = _read()
    current = str(state.get("stage") or "")
    if current not in STAGES:
        raise SystemExit("unknown release lifecycle stage")
    target_index = STAGES.index("claims_paused")
    current_index = STAGES.index(current)
    if current_index > target_index and not args.safety_pause:
        raise SystemExit(
            "claims can regress to paused only with --safety-pause after resume"
        )
    marker = {
        "paused": True,
        "reason": str(args.reason or "controlled_release").strip(),
        "at": _now(),
        "candidate_sha": state.get("candidate_sha"),
        "safety_pause": bool(args.safety_pause),
    }
    _write_claims_marker(marker)
    if current != "claims_paused":
        entered = _now()
        state["stage"] = "claims_paused"
        state["stage_entered_at"] = entered
        state.setdefault("history", []).append({
            "stage": "claims_paused", "at": entered,
            "safety_pause": bool(args.safety_pause),
        })
    state["pause_reason"] = marker["reason"]
    _save(
        state,
        "safety_claims_paused" if args.safety_pause else "claims_paused",
        {"reason": marker["reason"]},
    )
    print(json.dumps(marker, ensure_ascii=False, sort_keys=True))


def _cmd_resume_claims(args: argparse.Namespace) -> None:
    state = _read()
    authorization = state.get("resume_authorization") or {}
    if authorization.get("authorized") is not True:
        raise SystemExit("claims cannot resume without durable authorization")
    expected = _validate_sha(args.candidate_sha, "candidate SHA")
    if state.get("candidate_sha") != expected:
        raise SystemExit("claims resume candidate does not match lifecycle candidate")
    try:
        _claims_marker_path().unlink()
    except FileNotFoundError:
        pass
    _save(state, "claims_resumed", {"authorized_by": authorization.get("actor")})
    print(expected)


def _cmd_show(args: argparse.Namespace) -> None:
    state = _read()
    if args.field:
        value: Any = state
        for part in args.field.split("."):
            if not isinstance(value, dict) or part not in value:
                raise SystemExit(f"unknown lifecycle field: {args.field}")
            value = value[part]
        if isinstance(value, (dict, list)):
            print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        elif value is not None:
            print(value)
        return
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


def _cmd_assert(args: argparse.Namespace) -> None:
    state = _read()
    if state.get("stage") != args.stage:
        raise SystemExit(f"expected stage={args.stage}, found={state.get('stage')}")
    if args.candidate_sha:
        expected = _validate_sha(args.candidate_sha, "candidate SHA")
        if state.get("candidate_sha") != expected:
            raise SystemExit(
                f"candidate mismatch: expected={expected} found={state.get('candidate_sha')}"
            )
    print(args.stage)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--candidate-sha", required=True)
    prepare.add_argument("--previous-sha", required=True)
    prepare.add_argument("--impact-class", required=True)
    prepare.add_argument("--pause-reason", default="")
    prepare.add_argument("--expected-worker", action="append")
    prepare.add_argument("--pending-messages", type=int, default=0)
    prepare.add_argument("--force", action="store_true")
    prepare.add_argument("--force-reason", default="")
    prepare.set_defaults(func=_cmd_prepare)

    advance = commands.add_parser("advance")
    advance.add_argument("--stage", choices=STAGES, required=True)
    advance.add_argument("--reason", default="")
    advance.add_argument("--pending-messages", type=int)
    advance.add_argument("--gate", action="append", default=[])
    advance.add_argument("--safety-pause", action="store_true")
    advance.set_defaults(func=_cmd_advance)

    authorize = commands.add_parser("authorize-resume")
    authorize.add_argument("--actor", required=True)
    authorize.add_argument("--reason", required=True)
    authorize.set_defaults(func=_cmd_authorize)

    gate = commands.add_parser("record-gate")
    gate.add_argument("--gate", action="append", required=True)
    gate.set_defaults(func=_cmd_gate)

    pause_claims = commands.add_parser("pause-claims")
    pause_claims.add_argument("--reason", required=True)
    pause_claims.add_argument("--safety-pause", action="store_true")
    pause_claims.set_defaults(func=_cmd_pause_claims)

    resume_claims = commands.add_parser("resume-claims")
    resume_claims.add_argument("--candidate-sha", required=True)
    resume_claims.set_defaults(func=_cmd_resume_claims)

    show = commands.add_parser("show")
    show.add_argument("--field")
    show.set_defaults(func=_cmd_show)

    assertion = commands.add_parser("assert")
    assertion.add_argument("--stage", choices=STAGES, required=True)
    assertion.add_argument("--candidate-sha")
    assertion.set_defaults(func=_cmd_assert)
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
