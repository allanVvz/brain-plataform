from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.helpers.graphHierarchyAssertions import (
    run_all_validators,
    validateTreeViewUsesOnlyMainEdges,
)


def _load_fixture() -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "bra24_regression_fixture.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_valid_graph_passes_guardian_smoke() -> None:
    f = _load_fixture()
    graph = {"nodes": f["nodes"], "edges": f["valid_edges"]}
    ok, errors = run_all_validators(graph, f["tree_edge_ids_valid"])
    _assert(ok, f"expected valid graph to pass, got errors: {errors}")


def test_recurrent_critical_failures_are_detected() -> None:
    f = _load_fixture()
    graph = {"nodes": f["nodes"], "edges": f["valid_edges"] + f["invalid_edges"]}
    ok, errors = run_all_validators(graph, f["tree_edge_ids_valid"])
    _assert(not ok, "expected invalid graph to fail")
    joined = " | ".join(errors)
    _assert("forbidden edge product->embed" in joined, f"missing product->embed guard in {joined}")
    _assert("unapproved faq->embed" in joined or "is not approved before embed" in joined, f"missing FAQ approval guard in {joined}")


def test_tree_view_cannot_include_reference_edges() -> None:
    f = _load_fixture()
    graph = {"nodes": f["nodes"], "edges": f["valid_edges"] + f["invalid_edges"]}
    ok, errors = validateTreeViewUsesOnlyMainEdges(graph, f["tree_edge_ids_invalid"])
    _assert(not ok, "expected tree edge validator to fail with reference edges")
    _assert(any("is not main" in e for e in errors), f"expected non-main edge error, got {errors}")


def _has_graph_evidence(work_products: list[dict]) -> bool:
    graph_types = {"graph_node", "graph_edge", "graph_snapshot", "qa_graph_assertion"}
    return any(str(item.get("type") or "") in graph_types for item in (work_products or []))


def _run_completion_is_valid(run: dict) -> tuple[bool, str]:
    status = str(run.get("status") or "").lower()
    scope = str(run.get("task_scope") or "").lower()
    work_products = run.get("work_products") or []
    blocker = run.get("blocker")

    if scope in {"graph", "knowledge"}:
        if status == "done" and not _has_graph_evidence(work_products):
            return False, "done_without_graph_evidence"
        if status == "blocked" and not isinstance(blocker, dict):
            return False, "blocked_without_explicit_cause"
    return True, "ok"


def test_agent_run_requires_graph_evidence_or_explicit_blocker() -> None:
    f = _load_fixture()
    cases = f["agent_run_cases"]
    ok1, reason1 = _run_completion_is_valid(cases["valid_done_with_graph_evidence"])
    _assert(ok1, f"expected done+evidence to pass, got {reason1}")

    ok2, reason2 = _run_completion_is_valid(cases["valid_blocked_with_explicit_cause"])
    _assert(ok2, f"expected blocked+cause to pass, got {reason2}")

    ok3, reason3 = _run_completion_is_valid(cases["invalid_done_without_work_product"])
    _assert(not ok3 and reason3 == "done_without_graph_evidence", f"expected missing evidence failure, got {(ok3, reason3)}")


def main() -> None:
    test_valid_graph_passes_guardian_smoke()
    test_recurrent_critical_failures_are_detected()
    test_tree_view_cannot_include_reference_edges()
    test_agent_run_requires_graph_evidence_or_explicit_blocker()
    print("OK BRA-24 guardian smoke passed")


if __name__ == "__main__":
    main()
