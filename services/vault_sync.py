"""
Vault sync service: scans the local Obsidian vault and creates knowledge_items
with status='pending' for review in the Knowledge Validation queue.
"""
import os
import re
import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from services import supabase_client

VAULT_PATH = os.environ.get("VAULT_PATH", r"C:\Ai-Brain\Ai-Brain")

# Map vault folder names → persona slugs
_FOLDER_TO_SLUG: dict[str, str] = {
    "BAITA_CONVENIENCIA": "baita-conveniencia",
    "TOCK_FATAL": "tock-fatal",
    "VZ_LUPAS": "vz-lupas",
    "BAITA": "baita-conveniencia",
    "baita": "baita-conveniencia",
    "tock": "tock-fatal",
    "vz_lupas": "vz-lupas",
}

# Folders/files to always skip
_SKIP_DIRS = {".obsidian", ".git", "__pycache__", "node_modules", ".trash"}
_SKIP_FILES = {".DS_Store", "Thumbs.db"}

# Text-extractable extensions
_TEXT_EXTS = {".md", ".txt", ".json"}
_ASSET_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".mp4", ".pdf"}


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown. Returns (frontmatter_dict, body)."""
    if not content.startswith("---"):
        return {}, content
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
    if not match:
        return {}, content
    try:
        import yaml
        fm = yaml.safe_load(match.group(1)) or {}
    except Exception:
        fm = {}
    return fm, content[match.end():]


def _detect_persona(path: Path, frontmatter: dict) -> Optional[str]:
    """Determine persona slug from path or frontmatter."""
    # Explicit in frontmatter
    client_id = frontmatter.get("client_id") or frontmatter.get("cliente") or frontmatter.get("client")
    if client_id:
        normalized = str(client_id).upper().replace("-", "_").replace(" ", "_")
        if normalized in _FOLDER_TO_SLUG:
            return _FOLDER_TO_SLUG[normalized]
        return str(client_id).lower().replace("_", "-")

    # From path parts
    parts_upper = [p.upper().replace(" ", "_") for p in path.parts]
    for folder, slug in _FOLDER_TO_SLUG.items():
        if folder.upper() in parts_upper:
            return slug

    # projetos/{client}/ pattern
    for i, part in enumerate(path.parts):
        if part.lower() == "projetos" and i + 1 < len(path.parts):
            sub = path.parts[i + 1].lower()
            if "baita" in sub:
                return "baita-conveniencia"
            if "tock" in sub:
                return "tock-fatal"
            if "vz" in sub or "lupa" in sub:
                return "vz-lupas"

    return None


def _detect_content_type(path: Path, frontmatter: dict) -> str:
    """Detect knowledge content type from path + frontmatter."""
    # Explicit frontmatter
    fm_type = frontmatter.get("type") or frontmatter.get("tipo")
    if fm_type:
        type_map = {
            "brand": "brand", "marca": "brand",
            "briefing": "briefing",
            "product": "product", "produto": "product",
            "campaign": "campaign", "campanha": "campaign",
            "copy": "copy",
            "asset": "asset",
            "prompt": "prompt",
            "faq": "faq",
            "maker": "maker_material",
            "tone": "tone", "tom": "tone",
            "competitor": "competitor", "concorrente": "competitor",
            "audience": "audience", "persona": "audience",
            "rule": "rule", "regra": "rule",
        }
        return type_map.get(str(fm_type).lower(), "other")

    name = path.stem.lower()
    parts_lower = [p.lower() for p in path.parts]

    # Asset files
    if path.suffix.lower() in _ASSET_EXTS:
        return "asset"

    # Path-based detection (most reliable)
    if "01_brand_positioning" in name or name == "brand":
        return "brand"
    if "briefing" in name:
        return "briefing"
    if "tone" in name or "tom" in name:
        return "tone"
    if "audience" in name or "persona_buyer" in name:
        return "audience"
    if "moodboard" in name:
        return "maker_material"
    if "competitor" in parts_lower or "competitors" in parts_lower or name in {"nina_luxo", "supervaidosa", "zafira"}:
        return "competitor"
    if "07_prompts" in parts_lower or "prompts" in parts_lower:
        return "prompt"
    if "01_rules" in parts_lower or "rules" in parts_lower:
        return "rule"
    if "06_patterns" in parts_lower or "patterns" in parts_lower:
        return "rule"
    if "06_intents" in parts_lower or "intents" in parts_lower:
        return "rule"
    if "campanha" in parts_lower or "campanhas" in parts_lower or "campaign" in name:
        return "campaign"
    if "copie" in name or "copy" in name or "copies" in parts_lower:
        return "copy"
    if "produto" in name or "products" in name:
        return "product"
    if "faq" in name or "kb" in name:
        return "faq"
    if "02_skills" in parts_lower:
        return "prompt"
    if "04_memory" in parts_lower:
        return "other"
    if "projetos" in parts_lower:
        return "campaign"

    return "other"


def _file_title(path: Path, frontmatter: dict) -> str:
    """Generate a human-readable title for the knowledge item."""
    if frontmatter.get("title"):
        return str(frontmatter["title"])
    # Use stem, convert snake_case to title
    stem = path.stem.replace("_", " ").replace("-", " ")
    return stem.title()


def _should_skip(path: Path) -> bool:
    """Return True if file/dir should be excluded from sync."""
    for part in path.parts:
        if part in _SKIP_DIRS:
            return True
    if path.name in _SKIP_FILES:
        return True
    # Skip Obsidian internal files
    if path.suffix == ".md" and path.name.startswith("."):
        return True
    return False


def scan_vault(vault_path: str = VAULT_PATH) -> dict:
    """
    Scan the vault and return a preview of what would be synced.
    Returns: {files: [{path, persona, content_type, title}], total, by_client, by_type}
    """
    root = Path(vault_path)
    if not root.exists():
        return {"error": f"Vault path not found: {vault_path}", "files": []}

    files = []
    for fp in root.rglob("*"):
        if fp.is_dir() or _should_skip(fp):
            continue
        ext = fp.suffix.lower()
        if ext not in _TEXT_EXTS and ext not in _ASSET_EXTS:
            continue

        fm = {}
        if ext in _TEXT_EXTS:
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")
                if ext == ".md":
                    fm, _ = _parse_frontmatter(content)
            except Exception:
                pass

        persona_slug = _detect_persona(fp, fm)
        content_type = _detect_content_type(fp, fm)

        files.append({
            "path": str(fp.relative_to(root)),
            "full_path": str(fp),
            "persona": persona_slug,
            "content_type": content_type,
            "title": _file_title(fp, fm),
            "ext": ext,
        })

    by_client: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for f in files:
        k = f["persona"] or "unassigned"
        by_client[k] = by_client.get(k, 0) + 1
        by_type[f["content_type"]] = by_type.get(f["content_type"], 0) + 1

    return {"files": files, "total": len(files), "by_client": by_client, "by_type": by_type}


def run_sync(vault_path: str = VAULT_PATH, persona_filter: Optional[str] = None) -> dict:
    """
    Execute a full vault sync: create/update knowledge_items with status=pending.
    Returns summary with run_id and counts.
    """
    root = Path(vault_path)
    if not root.exists():
        return {"error": f"Vault path not found: {vault_path}"}

    # Get or create the vault knowledge source
    source = supabase_client.get_knowledge_source_by_path(vault_path)
    if not source:
        source = supabase_client.insert_knowledge_source({
            "source_type": "vault",
            "name": "AI Brain Vault",
            "path": vault_path,
        })

    source_id = source["id"]

    # Create sync run
    run = supabase_client.insert_sync_run({"source_id": source_id, "status": "running"})
    run_id = run["id"]

    counts = {"found": 0, "new": 0, "updated": 0, "skipped": 0}
    persona_cache: dict[str, Optional[str]] = {}  # slug → id

    def _get_persona_id(slug: Optional[str]) -> Optional[str]:
        if not slug:
            return None
        if slug not in persona_cache:
            p = supabase_client.get_persona(slug)
            persona_cache[slug] = p["id"] if p else None
        return persona_cache[slug]

    for fp in root.rglob("*"):
        if fp.is_dir() or _should_skip(fp):
            continue
        ext = fp.suffix.lower()
        if ext not in _TEXT_EXTS and ext not in _ASSET_EXTS:
            continue

        counts["found"] += 1
        rel_path = str(fp.relative_to(root))

        try:
            fm: dict = {}
            body = ""

            if ext in _TEXT_EXTS:
                raw = fp.read_text(encoding="utf-8", errors="ignore")
                if ext == ".md":
                    fm, body = _parse_frontmatter(raw)
                elif ext == ".json":
                    body = raw
                    try:
                        parsed = json.loads(raw)
                        fm = {"cliente": parsed.get("cliente", "")}
                    except Exception:
                        pass
                else:
                    body = raw
            else:
                body = f"[asset: {fp.name}]"

            persona_slug = _detect_persona(fp, fm)
            content_type = _detect_content_type(fp, fm)
            title = _file_title(fp, fm)

            # Apply persona filter if specified
            if persona_filter and persona_slug != persona_filter:
                counts["skipped"] += 1
                supabase_client.insert_sync_log({
                    "run_id": run_id, "file_path": rel_path,
                    "action": "skipped", "content_type": content_type,
                })
                continue

            persona_id = _get_persona_id(persona_slug)

            # Check if already exists
            existing = supabase_client.get_knowledge_item_by_path(rel_path)

            # Auto-assign status based on completeness
            if persona_id is None:
                auto_status = "needs_persona"
            elif content_type == "other":
                auto_status = "needs_category"
            else:
                auto_status = "pending"

            item_data = {
                "persona_id": persona_id,
                "source_id": source_id,
                "status": auto_status,
                "content_type": content_type,
                "title": title,
                "content": body[:8000],
                "metadata": {k: v for k, v in fm.items() if isinstance(v, (str, int, float, bool, list))},
                "file_path": rel_path,
                "file_type": ext.lstrip("."),
            }

            if existing:
                # Only update if content changed
                if existing["content"] != item_data["content"]:
                    item_data["status"] = existing.get("status", "pending")  # preserve approval state
                    supabase_client.update_knowledge_item(existing["id"], item_data)
                    counts["updated"] += 1
                    action = "updated"
                else:
                    counts["skipped"] += 1
                    action = "skipped"
            else:
                supabase_client.insert_knowledge_item(item_data)
                counts["new"] += 1
                action = "created"

            supabase_client.insert_sync_log({
                "run_id": run_id,
                "file_path": rel_path,
                "persona_id": persona_id,
                "action": action,
                "content_type": content_type,
            })

        except Exception as e:
            counts["skipped"] += 1
            supabase_client.insert_sync_log({
                "run_id": run_id,
                "file_path": rel_path,
                "action": "error",
                "error_message": str(e)[:500],
            })

    # Finalize run
    from datetime import datetime, timezone
    from services.event_emitter import emit as _emit
    supabase_client.update_sync_run(run_id, {
        "status": "completed",
        "files_found": counts["found"],
        "files_new": counts["new"],
        "files_updated": counts["updated"],
        "files_skipped": counts["skipped"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    supabase_client.update_knowledge_source(source_id, {
        "last_synced_at": datetime.now(timezone.utc).isoformat()
    })
    _emit("vault_sync_completed", entity_type="sync_run", entity_id=run_id, payload=counts)
    return {"run_id": run_id, **counts}
