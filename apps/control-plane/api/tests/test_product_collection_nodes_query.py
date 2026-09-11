"""``list_product_collection_nodes`` referenced an undefined ``offset`` name,
so every call raised ``NameError`` inside the ``try`` block and the broad
``except Exception`` swallowed it silently, always returning ``[]``.

That made every persona on the legacy (non-GraphBundle) menu path -- e.g.
baita-conveniencia, vz-lupas -- render `categories: []` even with a fully
populated graph, because ``build_menu_payload`` resolves categories from
this function.
"""
from __future__ import annotations

from repositories import control_plane


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return self

    def select(self, _fields):
        return self

    def eq(self, _field, _value):
        return self

    def neq(self, _field, _value):
        return self

    def order(self, _field, desc=False):
        return self

    def limit(self, _value):
        return self

    def range(self, _start, _end):
        return self

    def execute(self):
        return _FakeResult(self._rows)


def test_list_product_collection_nodes_returns_real_rows(monkeypatch):
    rows = [
        {"id": "group-1", "node_type": "product_group", "slug": "cervejas", "status": "validated"},
        {"id": "group-2", "node_type": "product_group", "slug": "bebidas-em-lata", "status": "validated"},
    ]
    monkeypatch.setattr(control_plane, "get_client", lambda: _FakeQuery(rows))

    result = control_plane.list_product_collection_nodes(
        persona_id="persona-1", node_type="product_group", limit=500,
    )

    assert result == rows
