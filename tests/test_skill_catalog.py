from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "skills" / "humanizer.json"

from api.services.skill_catalog import (  # noqa: E402
    SkillCatalogInvariantError,
    SkillManifestError,
    build_skill_rows,
    load_skill_manifest,
    manifest_checksum,
    sync_skill_manifest,
)


class FakeRepository:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.nodes: dict[tuple[str, str], dict] = {}
        self.edges: list[dict] = []
        self.writes: list[tuple[str, str]] = []

    def find_global_item(self, canonical_key: str):
        return self.items.get(canonical_key)

    def find_global_node(self, node_type: str, slug: str):
        return self.nodes.get((node_type, slug))

    def list_node_edges(self, node_id: str):
        return [
            edge for edge in self.edges
            if edge.get("source_node_id") == node_id or edge.get("target_node_id") == node_id
        ]

    def insert_item(self, payload: dict):
        self.writes.append(("insert", "knowledge_items"))
        self.items[payload["canonical_key"]] = dict(payload)
        return dict(payload)

    def update_item(self, item_id: str, payload: dict):
        self.writes.append(("update", "knowledge_items"))
        key = next(key for key, row in self.items.items() if row["id"] == item_id)
        self.items[key] = {**self.items[key], **payload}
        return dict(self.items[key])

    def insert_node(self, payload: dict):
        self.writes.append(("insert", "knowledge_nodes"))
        self.nodes[(payload["node_type"], payload["slug"])] = dict(payload)
        return dict(payload)

    def update_node(self, node_id: str, payload: dict):
        self.writes.append(("update", "knowledge_nodes"))
        key = next(key for key, row in self.nodes.items() if row["id"] == node_id)
        self.nodes[key] = {**self.nodes[key], **payload}
        return dict(self.nodes[key])


def _copy_catalog_fixture(tmp_path: Path) -> Path:
    skill_dir = tmp_path / ".agents" / "skills" / "humanizer"
    skill_dir.mkdir(parents=True)
    shutil.copy2(ROOT / ".agents" / "skills" / "humanizer" / "SKILL.md", skill_dir / "SKILL.md")
    shutil.copy2(ROOT / ".agents" / "skills" / "humanizer" / "LICENSE", skill_dir / "LICENSE")
    manifest_dir = tmp_path / "data" / "skills"
    manifest_dir.mkdir(parents=True)
    shutil.copy2(MANIFEST_PATH, manifest_dir / "humanizer.json")
    return manifest_dir / "humanizer.json"


def test_humanizer_manifest_matches_pinned_installation() -> None:
    manifest = load_skill_manifest(MANIFEST_PATH, repository_root=ROOT)

    assert manifest.schema_version == "BrainSkillManifestV1"
    assert manifest.name == "humanizer"
    assert manifest.version == "2.11.2"
    assert manifest.source_commit == "e2e92e7b4b8229253ed5c8e81dc65463fdeddda5"
    assert manifest.license_spdx == "MIT"
    assert manifest.skill_sha256 == "sha256:14fc8a965b6e0a8dc100ba4dffeab55cb94bbac112abbde7e014d5c15a35c202"


def test_manifest_rejects_path_outside_installed_skill(tmp_path: Path) -> None:
    path = _copy_catalog_fixture(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifact"]["skill_path"] = "../SKILL.md"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SkillManifestError, match="escapes the repository"):
        load_skill_manifest(path, repository_root=tmp_path)


def test_manifest_rejects_modified_artifact(tmp_path: Path) -> None:
    path = _copy_catalog_fixture(tmp_path)
    skill_path = tmp_path / ".agents" / "skills" / "humanizer" / "SKILL.md"
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nmodified\n", encoding="utf-8")

    with pytest.raises(SkillManifestError, match="checksum mismatch"):
        load_skill_manifest(path, repository_root=tmp_path)


def test_offline_dry_run_has_no_repository_or_edges() -> None:
    result = sync_skill_manifest(MANIFEST_PATH, repository_root=ROOT)

    assert result.dry_run is True
    assert result.database_inspected is False
    assert [(operation.resource, operation.action) for operation in result.operations] == [
        ("knowledge_item", "create"),
        ("knowledge_node", "create"),
        ("knowledge_edge", "noop"),
    ]
    assert result.active_edge_count == 0


def test_apply_is_idempotent_and_global_node_stays_disconnected() -> None:
    repository = FakeRepository()

    first = sync_skill_manifest(MANIFEST_PATH, repository, repository_root=ROOT, apply=True)
    first_writes = list(repository.writes)
    second = sync_skill_manifest(MANIFEST_PATH, repository, repository_root=ROOT, apply=True)

    assert [operation.action for operation in first.operations] == ["create", "create", "noop"]
    assert [operation.action for operation in second.operations] == ["noop", "noop", "noop"]
    assert repository.writes == first_writes
    assert first_writes == [("insert", "knowledge_items"), ("insert", "knowledge_nodes")]
    assert len(repository.items) == 1
    assert len(repository.nodes) == 1
    assert repository.edges == []

    item = next(iter(repository.items.values()))
    node = next(iter(repository.nodes.values()))
    assert item["persona_id"] is None
    assert item["content_type"] == "prompt"
    assert item["status"] == "approved"
    assert item["curation_status"] == "validated"
    assert item["agent_visibility"] == []
    assert node["persona_id"] is None
    assert node["node_type"] == "rule"
    assert node["source_table"] == "knowledge_items"
    assert node["source_id"] == item["id"]
    assert node["metadata"]["capability_kind"] == "skill"
    assert node["metadata"]["rag_eligible"] is False
    assert node["metadata"]["promote_to_kb"] is False
    assert node["metadata"]["prompt_injection"] == "disabled"
    assert node["metadata"]["connection_state"] == "disconnected"


def test_existing_active_edge_fails_closed_without_writes() -> None:
    repository = FakeRepository()
    manifest = load_skill_manifest(MANIFEST_PATH, repository_root=ROOT)
    item, node = build_skill_rows(
        manifest,
        repository_root=ROOT,
        catalog_checksum=manifest_checksum(MANIFEST_PATH),
    )
    repository.items[item["canonical_key"]] = item
    repository.nodes[(node["node_type"], node["slug"])] = node
    repository.edges.append({
        "id": "edge-1",
        "source_node_id": node["id"],
        "target_node_id": "persona-node",
        "relation_type": "visible_to_agent",
        "metadata": {"active": True},
    })

    with pytest.raises(SkillCatalogInvariantError, match="must stay disconnected"):
        sync_skill_manifest(MANIFEST_PATH, repository, repository_root=ROOT, apply=True)
    assert repository.writes == []
