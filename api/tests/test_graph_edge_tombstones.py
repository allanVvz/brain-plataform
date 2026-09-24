import pytest

from api.scripts.apply_graph_edge_tombstones import plan_tombstones


def test_bundle_without_visual_reconciliation_has_no_tombstones():
    assert plan_tombstones({"metadata": {}}, [], []) == []


def test_declared_tombstone_count_remains_strict():
    bundle = {
        "metadata": {
            "visual_media_reconciliation": {
                "soft_disabled_edges": [],
                "soft_disabled_edge_count": 1,
            }
        }
    }
    with pytest.raises(RuntimeError, match="soft_disabled_edge_count_mismatch"):
        plan_tombstones(bundle, [], [])
