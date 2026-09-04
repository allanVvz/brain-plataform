"""Versioned, graph-recoverable skill catalog contracts.

Skill Markdown is an inert text capability. Registering it here does not grant
tools, network access, code execution, RAG indexing, or prompt injection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal, Optional, Protocol
from urllib.parse import urlparse
import uuid


MANIFEST_VERSION = "BrainSkillManifestV1"
SKILL_PATH_PREFIX = PurePosixPath(".agents/skills")
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class SkillManifestError(ValueError):
    """The catalog manifest or installed artifact failed closed validation."""


class SkillCatalogInvariantError(RuntimeError):
    """Stored catalog state violates a global-skill invariant."""


@dataclass(frozen=True)
class BrainSkillManifestV1:
    """Validated catalog record for one installed Markdown skill."""

    schema_version: str
    name: str
    display_name: str
    version: str
    summary: str
    triggers: tuple[str, ...]
    limitations: tuple[str, ...]
    source_repository: str
    source_commit: str
    license_spdx: str
    license_path: str
    skill_path: str
    skill_sha256: str


SkillState = Literal["available", "projected", "connected", "drift"]


@dataclass(frozen=True)
class SkillProjection:
    """Future persona-scoped reference to a global manifest, never a copy."""

    persona_id: str
    skill_name: str
    manifest_checksum: str
    projection_node_id: str
    state: SkillState
    agent_slug: Optional[str] = None


@dataclass(frozen=True)
class ResolvedSkillContext:
    """Future fail-closed prompt input resolved for one persona-agent pair."""

    persona_id: str
    agent_slug: str
    skill_name: str
    version: str
    checksum: str
    trigger: str
    instructions: str


@dataclass(frozen=True)
class SkillSyncOperation:
    resource: Literal["knowledge_item", "knowledge_node", "knowledge_edge"]
    action: Literal["create", "update", "noop"]
    identity: str


@dataclass(frozen=True)
class SkillSyncResult:
    manifest: str
    manifest_checksum: str
    artifact_checksum: str
    dry_run: bool
    database_inspected: bool
    operations: tuple[SkillSyncOperation, ...]
    active_edge_count: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["operations"] = [asdict(operation) for operation in self.operations]
        return result


class SkillCatalogRepository(Protocol):
    def find_global_item(self, canonical_key: str) -> Optional[dict[str, Any]]: ...
    def find_global_node(self, node_type: str, slug: str) -> Optional[dict[str, Any]]: ...
    def list_node_edges(self, node_id: str) -> list[dict[str, Any]]: ...
    def insert_item(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def insert_node(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_node(self, node_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


def _object(value: Any, field: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SkillManifestError(f"{field} must be an object")
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise SkillManifestError(f"{field} missing fields: {sorted(missing)}")
    if unknown:
        raise SkillManifestError(f"{field} has unknown fields: {sorted(unknown)}")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillManifestError(f"{field} must be a non-empty string")
    return value.strip()


def _text_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise SkillManifestError(f"{field} must be a non-empty array")
    normalized = tuple(_text(item, field) for item in value)
    if len(set(normalized)) != len(normalized):
        raise SkillManifestError(f"{field} must not contain duplicates")
    return normalized


def _confined_path(repository_root: Path, raw: str, *, skill_name: str) -> Path:
    if "\\" in raw:
        raise SkillManifestError("artifact paths must use repository-relative POSIX separators")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise SkillManifestError(f"artifact path escapes the repository: {raw}")
    expected_prefix = (*SKILL_PATH_PREFIX.parts, skill_name)
    if relative.parts[: len(expected_prefix)] != expected_prefix:
        raise SkillManifestError(
            f"artifact path must stay under .agents/skills/{skill_name}: {raw}"
        )
    root = repository_root.resolve()
    resolved = (root / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SkillManifestError(f"artifact path escapes the repository: {raw}") from exc
    return resolved


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_checksum(manifest_path: Path) -> str:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _skill_frontmatter(skill_text: str) -> dict[str, str]:
    if not skill_text.startswith("---"):
        raise SkillManifestError("SKILL.md has no YAML frontmatter")
    parts = skill_text.split("---", 2)
    if len(parts) != 3:
        raise SkillManifestError("SKILL.md frontmatter is not closed")
    frontmatter = parts[1]

    def match(pattern: str, field: str) -> str:
        result = re.search(pattern, frontmatter, re.MULTILINE)
        if not result:
            raise SkillManifestError(f"SKILL.md frontmatter is missing {field}")
        return result.group(1).strip().strip('"\'')

    return {
        "name": match(r"^name:\s*([^\r\n]+)$", "name"),
        "license": match(r"^license:\s*([^\r\n]+)$", "license"),
        "version": match(r"^\s+version:\s*([^\r\n]+)$", "metadata.version"),
    }


def load_skill_manifest(
    manifest_path: Path,
    *,
    repository_root: Optional[Path] = None,
) -> BrainSkillManifestV1:
    """Load the manifest and verify the installed artifact, version, and license."""
    manifest_path = manifest_path.resolve()
    root = (repository_root or manifest_path.parents[2]).resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillManifestError(f"cannot read manifest {manifest_path}: {exc}") from exc

    top = _object(
        raw,
        "manifest",
        {
            "schema_version", "name", "display_name", "version", "summary",
            "triggers", "limitations", "source", "license", "artifact",
        },
        {
            "schema_version", "name", "display_name", "version", "summary",
            "triggers", "limitations", "source", "license", "artifact",
        },
    )
    source = _object(top["source"], "source", {"repository", "commit"}, {"repository", "commit"})
    license_data = _object(top["license"], "license", {"spdx", "path"}, {"spdx", "path"})
    artifact = _object(top["artifact"], "artifact", {"skill_path", "sha256"}, {"skill_path", "sha256"})

    schema_version = _text(top["schema_version"], "schema_version")
    name = _text(top["name"], "name")
    version = _text(top["version"], "version")
    commit = _text(source["commit"], "source.commit")
    checksum = _text(artifact["sha256"], "artifact.sha256")
    if schema_version != MANIFEST_VERSION:
        raise SkillManifestError(f"unsupported schema_version: {schema_version}")
    if not _NAME_RE.fullmatch(name):
        raise SkillManifestError(f"invalid skill name: {name}")
    if not _VERSION_RE.fullmatch(version):
        raise SkillManifestError(f"invalid semantic version: {version}")
    if not _COMMIT_RE.fullmatch(commit):
        raise SkillManifestError("source.commit must be a lowercase 40-character Git SHA")
    if not _SHA256_RE.fullmatch(checksum):
        raise SkillManifestError("artifact.sha256 must be a lowercase sha256 digest")
    if _text(license_data["spdx"], "license.spdx") != "MIT":
        raise SkillManifestError("manifest license must match the audited MIT artifact")
    repository_url = _text(source["repository"], "source.repository")
    parsed_repository = urlparse(repository_url)
    if parsed_repository.scheme != "https" or not parsed_repository.netloc:
        raise SkillManifestError("source.repository must be an absolute HTTPS URL")

    skill_path_text = _text(artifact["skill_path"], "artifact.skill_path")
    license_path_text = _text(license_data["path"], "license.path")
    skill_path = _confined_path(root, skill_path_text, skill_name=name)
    license_path = _confined_path(root, license_path_text, skill_name=name)
    if skill_path.name != "SKILL.md" or not skill_path.is_file():
        raise SkillManifestError(f"skill artifact is missing: {skill_path_text}")
    if license_path.name != "LICENSE" or not license_path.is_file():
        raise SkillManifestError(f"license artifact is missing: {license_path_text}")
    actual_checksum = sha256_file(skill_path)
    if actual_checksum != checksum:
        raise SkillManifestError(
            f"skill artifact checksum mismatch: expected {checksum}, got {actual_checksum}"
        )

    skill_text = skill_path.read_text(encoding="utf-8")
    frontmatter = _skill_frontmatter(skill_text)
    if frontmatter["name"] != name:
        raise SkillManifestError("manifest name does not match SKILL.md")
    if frontmatter["version"] != version:
        raise SkillManifestError("manifest version does not match SKILL.md")
    if frontmatter["license"] != "MIT":
        raise SkillManifestError("SKILL.md does not declare the MIT license")
    if not license_path.read_text(encoding="utf-8").startswith("MIT License"):
        raise SkillManifestError("LICENSE does not contain the MIT license text")

    return BrainSkillManifestV1(
        schema_version=schema_version,
        name=name,
        display_name=_text(top["display_name"], "display_name"),
        version=version,
        summary=_text(top["summary"], "summary"),
        triggers=_text_list(top["triggers"], "triggers"),
        limitations=_text_list(top["limitations"], "limitations"),
        source_repository=repository_url,
        source_commit=commit,
        license_spdx="MIT",
        license_path=license_path_text,
        skill_path=skill_path_text,
        skill_sha256=checksum,
    )


def _identity_uuid(kind: str, name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://brain-ai.local/{kind}/skill/{name}"))


def _common_metadata(manifest: BrainSkillManifestV1, catalog_checksum: str) -> dict[str, Any]:
    return {
        "capability_kind": "skill",
        "manifest_schema": manifest.schema_version,
        "manifest_checksum": catalog_checksum,
        "skill_name": manifest.name,
        "skill_version": manifest.version,
        "skill_summary": manifest.summary,
        "skill_triggers": list(manifest.triggers),
        "skill_limitations": list(manifest.limitations),
        "source_repository": manifest.source_repository,
        "source_commit": manifest.source_commit,
        "license": manifest.license_spdx,
        "license_path": manifest.license_path,
        "artifact_path": manifest.skill_path,
        "artifact_checksum": manifest.skill_sha256,
        "artifact_integrity": "valid",
        "catalog_scope": "global",
        "availability_state": "available",
        "connection_state": "disconnected",
        "projection": False,
        "rag_eligible": False,
        "promote_to_kb": False,
        "prompt_injection": "disabled",
        "executable": False,
    }


def build_skill_rows(
    manifest: BrainSkillManifestV1,
    *,
    repository_root: Path,
    catalog_checksum: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the global knowledge item and disconnected rule node."""
    skill_path = repository_root.resolve() / Path(*PurePosixPath(manifest.skill_path).parts)
    content = skill_path.read_text(encoding="utf-8")
    canonical_key = f"global:skill:{manifest.name}"
    common = _common_metadata(manifest, catalog_checksum)
    item_id = _identity_uuid("knowledge-item", manifest.name)
    item = {
        "id": item_id,
        "persona_id": None,
        "source_id": None,
        "status": "approved",
        "content_type": "prompt",
        "title": f"Skill: {manifest.display_name}",
        "content": content,
        "metadata": common,
        "tags": ["capability", "skill", manifest.name],
        "agent_visibility": [],
        "file_path": manifest.skill_path,
        "file_type": "md",
        "canonical_key": canonical_key,
        "canonical_hash": hashlib.sha256(canonical_key.encode("utf-8")).hexdigest(),
        "content_hash": manifest.skill_sha256.removeprefix("sha256:"),
        "git_commit_sha": manifest.source_commit,
        "curation_status": "validated",
        "confidence": 1.0,
    }
    node = {
        "id": _identity_uuid("knowledge-node", manifest.name),
        "persona_id": None,
        "source_table": "knowledge_items",
        "source_id": item_id,
        "node_type": "rule",
        "slug": f"skill-{manifest.name}",
        "title": f"Skill: {manifest.display_name}",
        "summary": manifest.summary,
        "tags": ["capability", "skill", manifest.name],
        "metadata": common,
        "status": "validated",
        "canonical_key": canonical_key,
        "confidence": 1.0,
    }
    return item, node


def _same_stored_fields(existing: Optional[dict[str, Any]], desired: dict[str, Any]) -> bool:
    if not existing:
        return False
    return all(existing.get(key) == value for key, value in desired.items() if key != "id")


def _active_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [edge for edge in edges if (edge.get("metadata") or {}).get("active") is not False]


def sync_skill_manifest(
    manifest_path: Path,
    repository: Optional[SkillCatalogRepository] = None,
    *,
    repository_root: Optional[Path] = None,
    apply: bool = False,
) -> SkillSyncResult:
    """Plan or apply an idempotent global skill registration.

    With no repository this is an offline dry-run. With a repository and
    ``apply=False`` it only reads current state. Writes require ``apply=True``.
    """
    if apply and repository is None:
        raise SkillCatalogInvariantError("apply requires a catalog repository")
    manifest_path = manifest_path.resolve()
    root = (repository_root or manifest_path.parents[2]).resolve()
    manifest = load_skill_manifest(manifest_path, repository_root=root)
    catalog_checksum = manifest_checksum(manifest_path)
    desired_item, desired_node = build_skill_rows(
        manifest,
        repository_root=root,
        catalog_checksum=catalog_checksum,
    )

    canonical_key = desired_item["canonical_key"]
    existing_item = repository.find_global_item(canonical_key) if repository else None
    existing_node = (
        repository.find_global_node(desired_node["node_type"], desired_node["slug"])
        if repository else None
    )
    edges = repository.list_node_edges(existing_node["id"]) if repository and existing_node else []
    active_edges = _active_edges(edges)
    if active_edges:
        edge_ids = sorted(str(edge.get("id") or "unknown") for edge in active_edges)
        raise SkillCatalogInvariantError(
            f"global skill node must stay disconnected; active edges: {edge_ids}"
        )

    item_action: Literal["create", "update", "noop"] = (
        "noop" if _same_stored_fields(existing_item, desired_item)
        else "update" if existing_item else "create"
    )
    node_for_compare = dict(desired_node)
    if existing_item:
        node_for_compare["source_id"] = existing_item["id"]
    node_action: Literal["create", "update", "noop"] = (
        "noop" if _same_stored_fields(existing_node, node_for_compare)
        else "update" if existing_node else "create"
    )

    if apply and repository:
        if existing_item:
            item_id = existing_item["id"]
            if item_action == "update":
                repository.update_item(item_id, {k: v for k, v in desired_item.items() if k != "id"})
        else:
            inserted_item = repository.insert_item(desired_item)
            item_id = str(inserted_item.get("id") or desired_item["id"])

        desired_node["source_id"] = item_id
        if existing_node:
            if node_action == "update":
                repository.update_node(
                    existing_node["id"],
                    {k: v for k, v in desired_node.items() if k != "id"},
                )
            node_id = existing_node["id"]
        else:
            inserted_node = repository.insert_node(desired_node)
            node_id = str(inserted_node.get("id") or desired_node["id"])
        active_edges = _active_edges(repository.list_node_edges(node_id))
        if active_edges:
            raise SkillCatalogInvariantError("skill registration unexpectedly created an active edge")

    operations = (
        SkillSyncOperation("knowledge_item", item_action, canonical_key),
        SkillSyncOperation("knowledge_node", node_action, desired_node["slug"]),
        SkillSyncOperation("knowledge_edge", "noop", "global-skill-disconnected"),
    )
    return SkillSyncResult(
        manifest=manifest.name,
        manifest_checksum=catalog_checksum,
        artifact_checksum=manifest.skill_sha256,
        dry_run=not apply,
        database_inspected=repository is not None,
        operations=operations,
        active_edge_count=len(active_edges),
    )


class SupabaseSkillCatalogRepository:
    """Small adapter kept outside normal runtime and RAG retrieval paths."""

    def __init__(self, client: Any = None) -> None:
        if client is None:
            from services import supabase_client

            client = supabase_client.get_client()
        self.client = client

    @staticmethod
    def _one_or_none(rows: list[dict[str, Any]], identity: str) -> Optional[dict[str, Any]]:
        if len(rows) > 1:
            raise SkillCatalogInvariantError(f"duplicate catalog records for {identity}")
        return rows[0] if rows else None

    def find_global_item(self, canonical_key: str) -> Optional[dict[str, Any]]:
        rows = (
            self.client.table("knowledge_items")
            .select("*")
            .eq("canonical_key", canonical_key)
            .is_("persona_id", "null")
            .limit(2)
            .execute()
            .data or []
        )
        return self._one_or_none(rows, canonical_key)

    def find_global_node(self, node_type: str, slug: str) -> Optional[dict[str, Any]]:
        rows = (
            self.client.table("knowledge_nodes")
            .select("*")
            .eq("node_type", node_type)
            .eq("slug", slug)
            .is_("persona_id", "null")
            .limit(2)
            .execute()
            .data or []
        )
        return self._one_or_none(rows, f"{node_type}:{slug}")

    def list_node_edges(self, node_id: str) -> list[dict[str, Any]]:
        source = (
            self.client.table("knowledge_edges")
            .select("id,source_node_id,target_node_id,relation_type,metadata")
            .eq("source_node_id", node_id)
            .execute()
            .data or []
        )
        target = (
            self.client.table("knowledge_edges")
            .select("id,source_node_id,target_node_id,relation_type,metadata")
            .eq("target_node_id", node_id)
            .execute()
            .data or []
        )
        return list({str(row.get("id")): row for row in [*source, *target]}.values())

    def insert_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.client.table("knowledge_items").insert(payload).execute()
        return (result.data or [payload])[0]

    def update_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.client.table("knowledge_items").update(payload).eq("id", item_id).execute()
        return (result.data or [{"id": item_id, **payload}])[0]

    def insert_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.client.table("knowledge_nodes").insert(payload).execute()
        return (result.data or [payload])[0]

    def update_node(self, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.client.table("knowledge_nodes").update(payload).eq("id", node_id).execute()
        return (result.data or [{"id": node_id, **payload}])[0]
