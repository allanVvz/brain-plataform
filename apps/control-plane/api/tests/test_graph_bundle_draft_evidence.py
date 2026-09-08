from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle_draft_evidence


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self.data = data
        self.limit_value = None

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        return _Response(self.data)


def test_select_one_handles_empty_postgrest_collection_without_maybe_single():
    query = _Query([])
    assert graph_bundle_draft_evidence._select_one(query) is None
    assert query.limit_value == 1


def test_select_one_returns_first_evidence_row():
    query = _Query([{"payload": {"ok": True}}, {"payload": {"ok": False}}])
    assert graph_bundle_draft_evidence._select_one(query) == {"payload": {"ok": True}}
