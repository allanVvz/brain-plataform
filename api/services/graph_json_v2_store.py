"""File-based versioning store for graph_json v2 — BRA-75 MVP.

Stores documents as `ai-brain/data/graph_documents/<persona_slug>.v<NNN>.json`.
This is the MVP storage; the production decision (Supabase v2 vs current
project, RFC 6902 vs domain-specific patch shape) is deferred to BRA-72 CTO.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from api.schemas.graph_json_v2 import GraphJson  # type: ignore
else:
    try:
        from schemas.graph_json_v2 import GraphJson
    except ModuleNotFoundError:  # pragma: no cover
        from api.schemas.graph_json_v2 import GraphJson


_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "graph_documents"


def _path(persona_slug: str, version: int) -> Path:
    return _DATA_ROOT / f"{persona_slug}.v{version:03d}.json"


def _checksum(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def list_versions(persona_slug: str) -> list[int]:
    if not _DATA_ROOT.exists():
        return []
    versions: list[int] = []
    for path in _DATA_ROOT.glob(f"{persona_slug}.v*.json"):
        try:
            versions.append(int(path.stem.split(".v")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(versions)


def load_version(persona_slug: str, version: int) -> "GraphJson | None":
    path = _path(persona_slug, version)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        wrapper = json.load(handle)
    return GraphJson.model_validate(wrapper["graph_json"])


def load_current(persona_slug: str) -> "tuple[int, GraphJson] | None":
    versions = list_versions(persona_slug)
    if not versions:
        return None
    latest = versions[-1]
    graph = load_version(persona_slug, latest)
    if graph is None:
        return None
    return latest, graph


def save_version(persona_slug: str, version: int, graph: "GraphJson") -> str:
    _DATA_ROOT.mkdir(parents=True, exist_ok=True)
    graph_dict = graph.model_dump()
    cs = _checksum(graph_dict)
    wrapper = {
        "version": version,
        "persona_slug": persona_slug,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "checksum": cs,
        "graph_json": graph_dict,
    }
    target = _path(persona_slug, version)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(wrapper, handle, indent=2, ensure_ascii=False)
    return cs


def storage_root() -> Path:
    return _DATA_ROOT
