from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_approve_product_does_not_mark_related_faqs(monkeypatch):
    from routes import knowledge

    product = {
        "id": "product-1",
        "persona_id": "persona-1",
        "node_type": "product",
        "slug": "lagunitas-daytime-355ml",
        "title": "Lagunitas Day Time 355ml",
        "metadata": {"category_slug": "cervejas-premium"},
        "status": "pending_validation",
    }
    calls = {}

    monkeypatch.setattr(knowledge.supabase_client, "get_persona_by_id", lambda persona_id: {"id": persona_id, "slug": "baita-conveniencia"})
    monkeypatch.setattr(knowledge.auth_service, "assert_persona_access", lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge.auth_service, "current_user", lambda request: {"id": "user-1", "role": "admin"})
    monkeypatch.setattr(knowledge.supabase_client, "get_knowledge_node_by_slug", lambda *args, **kwargs: product)

    def fake_update(node_id, data, **kwargs):
        calls["node_id"] = node_id
        calls["data"] = data
        calls["kwargs"] = kwargs
        return {**product, **data}

    monkeypatch.setattr(knowledge.supabase_client, "update_knowledge_node", fake_update)
    monkeypatch.setattr(knowledge, "_decorate_products", lambda rows: rows)
    monkeypatch.setattr(knowledge, "emit", lambda *args, **kwargs: None)

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-1", "role": "admin"}))
    result = knowledge.approve_product("lagunitas-daytime-355ml", request, persona_id="persona-1")

    assert result["ok"] is True
    assert result["product"]["status"] == "validated"
    assert calls["node_id"] == "product-1"
    assert calls["kwargs"] == {"mark_related_faqs": False}
