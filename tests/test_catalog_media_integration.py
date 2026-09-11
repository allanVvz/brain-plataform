"""Offline projection/proof/transport regressions; no outbound or backend."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


site = load("catalog_site_blocks", "apps/control-plane/api/services/site_blocks.py")
transport = load("catalog_response_test", "apps/transport/api/services/catalog_response.py")
plan = load("catalog_plan_test", "apps/control-plane/api/services/catalog_media_plan.py")


@pytest.fixture
def bundle():
    return json.loads((ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v16-voice-reachable.json").read_text(encoding="utf-8"))


def test_both_branches_keep_catalog_images_and_separate_prices(bundle):
    outputs = [site.resolve_blocks(bundle, template_key="landing_page", scope=scope)
               for scope in ["audience:tock-retail", "audience:tock-reseller"]]
    for output in outputs:
        groups = next(b["data"]["groups"] for b in output["blocks"] if b["kind"] == "group_index")
        image_groups = [g for g in groups if g["cover"]]
        assert image_groups
        assert all(g["cover"]["asset_node_id"] == g["assets"][0]["asset_node_id"] for g in image_groups)
    prices = [next(b["data"] for b in o["blocks"] if b["kind"] == "price_range") for o in outputs]
    assert prices[0] != prices[1]


def test_assignment_retry_preserves_order_pin_and_unlink_keep_node(bundle):
    asset = next(n for n in bundle["nodes"] if n["node_type"] == "asset" and n["data"].get("product_node_id"))
    operation = {"operation_id": "one", "owner_node_id": asset["data"]["product_node_id"],
                 "asset_node_id": asset["id"], "action": "assign", "assigned_at": "2026-09-01T00:00:00Z"}
    assigned = plan.edit_bundle(bundle, [operation], actor_id="operator")
    assert assigned == plan.edit_bundle(assigned, [operation], actor_id="operator")
    pinned = plan.edit_bundle(assigned, [{**operation, "operation_id": "two", "action": "pin"}], actor_id="operator")
    unlinked = plan.edit_bundle(pinned, [{**operation, "operation_id": "three", "action": "unlink"}], actor_id="operator")
    assert len(bundle["nodes"]) == len(unlinked["nodes"])
    nodes = {n["id"]: n for n in unlinked["nodes"]}
    scoped = site.branch_closure(nodes, unlinked["edges"], "audience:tock-retail")
    media = site.resolve_catalog_media(unlinked["nodes"], unlinked["edges"], persona_id=bundle["persona"]["id"], scoped_ids=scoped, owner_id=operation["owner_node_id"])
    assert not media["assets"]


def test_response_three_images_and_text_persist_individual_receipts_once():
    calls, stored = [], {}
    items = [{"text": "Model reply"}, *[{"asset_node_id": str(i)} for i in range(3)]]
    def persist(journal):
        stored.clear(); stored.update(deepcopy(journal))
    def send(item):
        calls.append(item); return {"id": f"receipt-{len(calls)}"}
    kwargs = dict(response_id="response", persist=persist, send=send, authorize=lambda item: None)
    transport.send_items(items, journal={}, **kwargs)
    transport.send_items(items, journal=stored, **kwargs)
    assert len(calls) == 4
    assert len(stored) == 4
    assert all(item["status"] == "completed" for item in stored.values())


def test_uncertain_item_never_retries_completed_text_or_image():
    stored, calls = {}, []
    def persist(journal):
        stored.clear(); stored.update(deepcopy(journal))
    def send(item):
        calls.append(item)
        if item.get("asset_node_id"):
            raise TimeoutError("unknown provider result")
        return {"id": "text-receipt"}
    kwargs = dict(response_id="response", persist=persist, send=send, authorize=lambda item: None)
    items = [{"text": "Reply"}, {"asset_node_id": "image"}]
    with pytest.raises(TimeoutError):
        transport.send_items(items, journal={}, **kwargs)
    with pytest.raises(transport.ReconciliationRequired):
        transport.send_items(items, journal=stored, **kwargs)
    assert len(calls) == 2


def test_cas_failure_before_send_never_calls_provider():
    def fail(_): raise transport.ReconciliationRequired("CAS conflict")
    def forbidden(_): pytest.fail("provider called before journal commit")
    with pytest.raises(transport.ReconciliationRequired):
        transport.send_items([{"text": "Reply"}], response_id="r", journal={}, persist=fail,
                             send=forbidden, authorize=lambda item: None)
