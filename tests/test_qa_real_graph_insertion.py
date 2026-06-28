from __future__ import annotations

import json
import os
import time
import uuid
from urllib import error, parse, request

import pytest


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _http_json(method: str, base: str, path: str, *, token: str, body: dict | None = None, timeout: float = 45.0) -> dict:
    url = base.rstrip("/") + path
    headers = {
        "Accept": "application/json",
        "X-AI-BRAIN-ADMIN-TOKEN": token,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = request.Request(url, method=method, headers=headers, data=data)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise AssertionError(f"{method} {path} failed with HTTP {exc.code}: {detail[:1200]}") from exc


def _http_error(method: str, base: str, path: str, *, token: str, body: dict | None = None, timeout: float = 45.0) -> tuple[int, str]:
    url = base.rstrip("/") + path
    headers = {
        "Accept": "application/json",
        "X-AI-BRAIN-ADMIN-TOKEN": token,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = request.Request(url, method=method, headers=headers, data=data)
    try:
        with request.urlopen(req, timeout=timeout):
            return 200, ""
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _persona_ref() -> str:
    return _env("QA_PERSONA_REF", _env("QA_PERSONA_SLUG", "vz-lupas"))


def _graph_nodes(base: str, token: str, *, mode: str = "graph") -> list[dict]:
    graph = _http_json(
        "GET",
        base,
        "/knowledge/graph-data?" + parse.urlencode({"persona_slug": _persona_ref(), "mode": mode}),
        token=token,
    )
    return graph.get("nodes") or []


def _find_node_id_by_source_item(nodes: list[dict], source_item_id: str, expected_type: str) -> str:
    for node in nodes:
        data = node.get("data") or {}
        if (
            data.get("source_table") == "knowledge_items"
            and str(data.get("source_id") or "") == str(source_item_id)
            and str(data.get("node_type") or "").lower() == expected_type.lower()
        ):
            node_id = str(node.get("id") or "")
            if node_id.startswith("gn:"):
                return node_id[3:]
            return node_id
    return ""


@pytest.mark.integration
def test_qa_contract_real_graph_insertion() -> None:
    if _env("QA_REAL_GRAPH_INSERTION_TEST") != "1":
        pytest.skip("Set QA_REAL_GRAPH_INSERTION_TEST=1 to run QA live insertion test.")

    base = _env("API_BASE", "http://localhost:8000")
    token = _env("AI_BRAIN_ADMIN_TEST_TOKEN")
    if not token:
        pytest.skip("Set AI_BRAIN_ADMIN_TEST_TOKEN to run QA live insertion test.")

    run_token = uuid.uuid4().hex[:10]
    title_product = f"QA Graph Product {run_token}"
    title_faq_pending = f"QA Graph FAQ Pending {run_token}"
    title_faq_approved = f"QA Graph FAQ Approved {run_token}"
    ingest = _http_json(
        "POST",
        base,
        "/api/catalog/ingest",
        token=token,
        body={
            "persona_ref": _persona_ref(),
            "source_ref": f"qa-real-graph-test:{run_token}",
            "entries": [
                {
                    "title": title_product,
                    "content": f"Produto de teste run_id={run_token}.",
                    "content_type": "product",
                    "tags": ["qa", "graph", run_token],
                    "metadata": {"qa_test_run_token": run_token},
                },
                {
                    "title": title_faq_pending,
                    "content": f"Pergunta: FAQ pendente run_id={run_token}? Resposta: Ainda pendente.",
                    "content_type": "faq",
                    "tags": ["qa", "faq", "pending", run_token],
                    "metadata": {"qa_test_run_token": run_token, "run_id": run_token},
                },
                {
                    "title": title_faq_approved,
                    "content": f"Pergunta: FAQ aprovada run_id={run_token}? Resposta: Esta aprovada para embed.",
                    "content_type": "faq",
                    "tags": ["qa", "faq", "approved", run_token],
                    "metadata": {"qa_test_run_token": run_token, "run_id": run_token},
                }
            ],
        },
    )
    assert ingest.get("ok") is True
    assert ingest.get("drafts_created") == 3
    items = ingest.get("items") or []
    assert len(items) == 3, ingest
    product_item_id = str(items[0].get("id") or "")
    faq_pending_item_id = str(items[1].get("id") or "")
    faq_approved_item_id = str(items[2].get("id") or "")
    assert product_item_id and faq_pending_item_id and faq_approved_item_id, ingest

    generated = _http_json(
        "POST",
        base,
        "/api/graph/generate",
        token=token,
        body={"persona_ref": _persona_ref()},
    )
    assert generated.get("ok") is True

    product_node_id = ""
    faq_pending_node_id = ""
    faq_approved_node_id = ""
    for _ in range(8):
        nodes = _graph_nodes(base, token, mode="graph")
        product_node_id = _find_node_id_by_source_item(nodes, product_item_id, "product")
        faq_pending_node_id = _find_node_id_by_source_item(nodes, faq_pending_item_id, "faq")
        faq_approved_node_id = _find_node_id_by_source_item(nodes, faq_approved_item_id, "faq")
        if product_node_id and faq_pending_node_id and faq_approved_node_id:
            break
        time.sleep(1.5)

    assert product_node_id, f"product node not mirrored in graph for item {product_item_id}"
    assert faq_pending_node_id, f"pending faq node not mirrored in graph for item {faq_pending_item_id}"
    assert faq_approved_node_id, f"approved faq candidate node not mirrored in graph for item {faq_approved_item_id}"

    # Product -> Embed direct must fail.
    direct_status, direct_body = _http_error(
        "POST",
        base,
        "/knowledge/graph-edges",
        token=token,
        body={
            "source_node_id": f"gn:{product_node_id}",
            "target_node_id": "embedded",
            "relation_type": "manual",
        },
    )
    assert direct_status in {400, 409}, direct_body

    # Unapproved FAQ -> Embed must fail.
    unapproved_status, unapproved_body = _http_error(
        "POST",
        base,
        "/knowledge/graph-edges",
        token=token,
        body={
            "source_node_id": f"gn:{faq_pending_node_id}",
            "target_node_id": "embedded",
            "relation_type": "manual",
        },
    )
    assert unapproved_status in {400, 409}, unapproved_body

    approve = _http_json(
        "POST",
        base,
        "/api/faq/approve",
        token=token,
        body={"persona_ref": _persona_ref(), "knowledge_item_id": faq_approved_item_id},
    )
    assert approve.get("ok") is True, approve

    # Refresh graph mirrors after approval.
    regen = _http_json(
        "POST",
        base,
        "/api/graph/generate",
        token=token,
        body={"persona_ref": _persona_ref()},
    )
    assert regen.get("ok") is True, regen

    faq_approved_node_id = ""
    for _ in range(6):
        nodes = _graph_nodes(base, token, mode="graph")
        faq_approved_node_id = _find_node_id_by_source_item(nodes, faq_approved_item_id, "faq")
        if faq_approved_node_id:
            break
        time.sleep(1.0)
    assert faq_approved_node_id, "approved FAQ node id not found after approval and graph rebuild"

    embed_generated = _http_json(
        "POST",
        base,
        "/api/embeds/generate",
        token=token,
        body={"persona_ref": _persona_ref(), "faq_node_id": faq_approved_node_id},
    )
    assert embed_generated.get("ok") is True, embed_generated
    publication = embed_generated.get("publication") or {}
    assert publication.get("embedded_edge_id"), embed_generated

    # Semantic tree representation must contain this run's mirrored nodes.
    tree_nodes = _graph_nodes(base, token, mode="semantic_tree")
    run_ids_found = 0
    for source_item_id in (product_item_id, faq_pending_item_id, faq_approved_item_id):
        node_id = _find_node_id_by_source_item(tree_nodes, source_item_id, "product" if source_item_id == product_item_id else "faq")
        if node_id:
            run_ids_found += 1
    assert run_ids_found == 3, f"semantic_tree did not expose all run nodes for run_id={run_token}"
