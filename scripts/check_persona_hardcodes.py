"""Fail CI when persona commercial facts escape canonical Markdown."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "docs" / "sdr"
FORBIDDEN_FILES = {
    ROOT / "api" / "scripts" / "seed_baita_full_menu.py",
    ROOT / "api" / "scripts" / "publish_baita_pilot_faqs.py",
    ROOT / "api" / "n8n-workflows" / "Tock Vitoria Crm Low.json",
    ROOT / "api" / "n8n-workflows" / "Kb Update Tock.json",
}
FORBIDDEN_MARKERS = {
    "MENU_TEXT",
    "wa-wscrap-bot",
    "_run_baita_safe",
    "Simple Vector Store",
    "Tock Vitoria Crm Low",
    "https://api.vzforeal.com",
}

RUNTIME_ROOTS = (
    ROOT / "api" / "routes",
    ROOT / "api" / "services",
    ROOT / "api" / "core",
    ROOT / "api" / "workers",
    ROOT / "api" / "scripts",
    ROOT / "api" / "n8n-workflows",
    ROOT / "dashboard" / "app",
    ROOT / "dashboard" / "components",
    ROOT / "dashboard" / "lib",
    ROOT / "dashboard" / "scripts",
    ROOT / ".github",
    ROOT / "ops",
)
RUNTIME_SUFFIXES = {".py", ".json", ".js", ".mjs", ".ts", ".tsx", ".sh", ".yml", ".yaml"}


def frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---", raw, re.S)
    return yaml.safe_load(match.group(1)) if match else {}


def facts() -> set[str]:
    values: set[str] = set()
    for path in DOCUMENTS.glob("*/products/*.md"):
        meta = frontmatter(path) or {}
        for value in (
            meta.get("title"),
            (meta.get("metadata") or {}).get("display_name"),
            (meta.get("metadata") or {}).get("source_text"),
            (meta.get("metadata") or {}).get("price_display"),
        ):
            text = str(value or "").strip()
            if len(text) >= 8:
                values.add(text)
    return values


def main() -> None:
    errors: list[str] = []
    for path in FORBIDDEN_FILES:
        if path.exists():
            errors.append(f"legacy hardcoded file still exists: {path.relative_to(ROOT)}")

    commercial_facts = facts()
    source_files = sorted({
        path
        for root in RUNTIME_ROOTS
        if root.exists()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in RUNTIME_SUFFIXES
        and not {"e2e", "__tests__", "fixtures", "__pycache__"}.intersection(path.parts)
    })
    source_files.extend([ROOT / "docker-compose.yml", ROOT / "dashboard" / "next.config.js"])
    workflow_files = [path for path in source_files if path.suffix == ".json"]
    for path in source_files:
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                errors.append(f"{path.relative_to(ROOT)} contains forbidden marker {marker!r}")
        for fact in commercial_facts:
            if fact in text:
                errors.append(
                    f"{path.relative_to(ROOT)} contains product fact from Markdown: {fact!r}"
                )
                break
        if path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.relative_to(ROOT)} is invalid JSON: {exc}")
            if re.search(r"R\$\s*\d", text, re.I):
                errors.append(f"{path.relative_to(ROOT)} contains an embedded price")

    if errors:
        raise SystemExit("\n".join(sorted(set(errors))))
    print(
        json.dumps(
            {
                "ok": True,
                "commercial_facts_checked": len(commercial_facts),
                "python_files_checked": len(source_files),
                "workflows_checked": len(workflow_files),
            }
        )
    )


if __name__ == "__main__":
    main()
