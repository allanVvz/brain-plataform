"""Build the repository manifest and GraphBundle for Tock Fatal identity.

This is a local, deterministic build step. It never connects to production,
publishes a graph, uploads media, or changes a database. Official source files
are copied byte-for-byte into the dashboard's public directory only for the
small runtime set selected below; the complete source archive remains under
``assets/brands/tock-fatal/source``.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "assets" / "brands" / "tock-fatal" / "source"
MANIFEST_PATH = ROOT / "assets" / "brands" / "tock-fatal" / "manifest.json"
PUBLIC_ROOT = ROOT / "dashboard" / "public" / "brands" / "tock-fatal"
PUBLIC_STYLESHEET = PUBLIC_ROOT / "brand.css"
BASE_BUNDLE = (
    ROOT
    / "data"
    / "graph_bundles"
    / "tock-fatal"
    / "sdr-qualification-v12-model-owned.json"
)
OUTPUT_BUNDLE = (
    ROOT
    / "data"
    / "graph_bundles"
    / "tock-fatal"
    / "sdr-qualification-v13-brand-identity.json"
)

OFFICIAL_SOURCE = "operator_supplied_identity_package_2026-09-04"
MANUAL_SOURCE_PATH = "assets/brands/tock-fatal/source/Manual de marca/Manual de marca atualizado.pdf"
FONT_FAMILY = "Bodrum Sweet"
FONT_STYLE = "13 Light"


WEB_ASSETS = {
    "logo-wordmark-retail.png": Path("Logo Transparente") / "rosa 2.png",
    "logo-wordmark-atacado.png": Path("Logo dourada") / "lodo dourada.png",
    "logo-wordmark-reverse.png": Path("Logo Transparente") / "branca reta sem brilho.png",
    "logo-round-retail.png": Path("Logo Transparente") / "redonda rosa 3.png",
    "logo-round-atacado.png": Path("Logo dourada") / "dourada 3.png",
    "bodrum-sweet-13-light.otf": Path("Fonte") / "bodrum-sweet-13-light.otf",
}


BRANCHES = {
    "varejo": {
        "brand_id": "brand:tock-fatal-varejo",
        "logo": "logo-wordmark-retail.png",
        "round_logo": "logo-round-retail.png",
        "palette": {
            "primary": "#9F2960",
            "secondary": "#B55A69",
            "accent": "#FBD0D9",
            "surface": "#FFF7FA",
            "text": "#3C1726",
        },
    },
    "atacado": {
        "brand_id": "brand:tock-fatal-atacado",
        "logo": "logo-wordmark-atacado.png",
        "round_logo": "logo-round-atacado.png",
        "palette": {
            "primary": "#922B48",
            "secondary": "#9F2960",
            "accent": "#CEA265",
            "surface": "#FFF8F1",
            "text": "#2E111C",
        },
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _role(relative: Path) -> str:
    lowered = relative.as_posix().lower()
    if "/logo " in f"/{lowered}" or lowered.startswith("logo "):
        return "logo-variant"
    if lowered.endswith((".otf", ".ttf", ".woff", ".woff2")):
        return "font-file"
    if "manual de marca" in lowered:
        return "brandbook"
    if "paleta de cores" in lowered:
        return "palette"
    if "fachada" in lowered:
        return "signage"
    if "etiqueta" in lowered:
        return "label"
    if "cartão visita" in lowered or "cartao visita" in lowered:
        return "business-card"
    if "sacola" in lowered:
        return "packaging"
    return "representative-visual"


def build_manifest() -> dict:
    if not SOURCE_ROOT.is_dir():
        raise SystemExit(f"identity source directory not found: {SOURCE_ROOT}")
    files = []
    for path in sorted(item for item in SOURCE_ROOT.rglob("*") if item.is_file()):
        relative = path.relative_to(SOURCE_ROOT)
        files.append(
            {
                "path": relative.as_posix(),
                "repository_path": path.relative_to(ROOT).as_posix(),
                "role": _role(relative),
                "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "brand": "Tock Fatal",
        "source": OFFICIAL_SOURCE,
        "status": "validated",
        "source_root": SOURCE_ROOT.relative_to(ROOT).as_posix(),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }


def copy_web_assets() -> dict[str, dict]:
    mimetypes.add_type("font/otf", ".otf")
    PUBLIC_ROOT.mkdir(parents=True, exist_ok=True)
    copied: dict[str, dict] = {}
    for public_name, source_relative in WEB_ASSETS.items():
        source = SOURCE_ROOT / source_relative
        target = PUBLIC_ROOT / public_name
        if not source.is_file():
            raise SystemExit(f"official web asset not found: {source}")
        shutil.copyfile(source, target)
        copied[public_name] = {
            "url": f"/brands/tock-fatal/{public_name}",
            "repository_path": target.relative_to(ROOT).as_posix(),
            "source_repository_path": source.relative_to(ROOT).as_posix(),
            "sha256": _sha256(target),
            "mime": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        }
    return copied


def write_web_stylesheet() -> None:
    PUBLIC_STYLESHEET.write_text(
        """@font-face {
  font-family: \"Bodrum Sweet\";
  src: url(\"./bodrum-sweet-13-light.otf\") format(\"opentype\");
  font-style: normal;
  font-weight: 300;
  font-display: swap;
}

[data-brand-family=\"tock-fatal\"] {
  color: var(--brand-text);
  background-color: var(--brand-surface);
}

[data-brand-family=\"tock-fatal\"] :is(h1, h2, h3, .brand-display) {
  font-family: \"Bodrum Sweet\", \"Inter\", \"Segoe UI\", Arial, sans-serif;
  font-weight: 300;
}

[data-brand-family=\"tock-fatal\"][data-brand-channel=\"varejo\"] {
  --brand-primary: #9F2960;
  --brand-secondary: #B55A69;
  --brand-accent: #FBD0D9;
  --brand-surface: #FFF7FA;
  --brand-text: #3C1726;
}

[data-brand-family=\"tock-fatal\"][data-brand-channel=\"atacado\"] {
  --brand-primary: #922B48;
  --brand-secondary: #9F2960;
  --brand-accent: #CEA265;
  --brand-surface: #FFF8F1;
  --brand-text: #2E111C;
}
""",
        encoding="utf-8",
        newline="\n",
    )


def _visual_identity(channel: str, copied: dict[str, dict]) -> dict:
    branch = BRANCHES[channel]
    palette = branch["palette"]
    return {
        "channel": channel,
        "stylesheet_url": "/brands/tock-fatal/brand.css",
        "html_attributes": {
            "data-brand-family": "tock-fatal",
            "data-brand-channel": channel,
        },
        "logo": {
            "primary": copied[branch["logo"]],
            "round": copied[branch["round_logo"]],
            "reverse": copied["logo-wordmark-reverse.png"],
            "alt": f"Tock Fatal {channel.title()}",
        },
        "palette": palette,
        "typography": {
            "display": {
                "family": FONT_FAMILY,
                "style": FONT_STYLE,
                "weight": 300,
                **copied["bodrum-sweet-13-light.otf"],
            },
            "body": {
                "family": "Inter",
                "fallbacks": ["Segoe UI", "Arial", "sans-serif"],
            },
        },
        "css_variables": {
            "--brand-primary": palette["primary"],
            "--brand-secondary": palette["secondary"],
            "--brand-accent": palette["accent"],
            "--brand-surface": palette["surface"],
            "--brand-text": palette["text"],
            "--brand-display-font": f'"{FONT_FAMILY}"',
        },
        "source": OFFICIAL_SOURCE,
        "manual_source_path": MANUAL_SOURCE_PATH,
        "status": "validated",
    }


def _asset_node(channel: str, role: str, media: dict, title: str) -> dict:
    node_id = f"asset:tock-brand-{channel}-{role}"
    return {
        "id": node_id,
        "node_type": "asset",
        "slug": node_id.removeprefix("asset:"),
        "title": title,
        "summary": f"Ativo oficial da identidade Tock Fatal aplicado ao canal {channel}.",
        "tags": ["identidade-visual", "tock-fatal", channel, role],
        "status": "validated",
        "data": {
            "source": OFFICIAL_SOURCE,
            "status": "validated",
            "asset_role": role,
            "channel": channel,
            "media": media,
        },
    }


def build_bundle(copied: dict[str, dict], manifest: dict) -> dict:
    bundle = json.loads(BASE_BUNDLE.read_text(encoding="utf-8"))
    bundle = deepcopy(bundle)
    bundle["metadata"] = {
        **bundle["metadata"],
        "purpose": "tock_fatal_v13_brand_identity",
        "content_revision": "3.2-brand-identity",
        "baseline_publication": {
            "version": 12,
            "source_bundle": BASE_BUNDLE.relative_to(ROOT).as_posix(),
        },
        "brand_identity_source": OFFICIAL_SOURCE,
        "brand_identity_manifest": MANIFEST_PATH.relative_to(ROOT).as_posix(),
        "brand_identity_file_count": manifest["file_count"],
        "publication_allowed": False,
        "draft_note": (
            "Identidade oficial incorporada e validada localmente. Publicacao produtiva "
            "continua pendente de dry-run e autorizacao explicita separada."
        ),
    }

    by_id = {node["id"]: node for node in bundle["nodes"]}
    new_nodes = []
    new_edges = []
    for channel, branch in BRANCHES.items():
        brand = by_id[branch["brand_id"]]
        identity = _visual_identity(channel, copied)
        brand["data"] = {**(brand.get("data") or {}), "visual_identity": identity}

        media_by_role = {
            "brand_logo": identity["logo"]["primary"],
            "brand_logo_round": identity["logo"]["round"],
            "brand_logo_reverse": identity["logo"]["reverse"],
            "brand_font": identity["typography"]["display"],
        }
        titles = {
            "brand_logo": f"Logo oficial Tock Fatal — {channel}",
            "brand_logo_round": f"Logo circular oficial Tock Fatal — {channel}",
            "brand_logo_reverse": f"Logo reverso oficial Tock Fatal — {channel}",
            "brand_font": f"Fonte oficial {FONT_FAMILY} {FONT_STYLE} — {channel}",
        }
        identity["asset_node_ids"] = {}
        for role, media in media_by_role.items():
            node = _asset_node(channel, role, media, titles[role])
            new_nodes.append(node)
            identity["asset_node_ids"][role] = node["id"]
            new_edges.append(
                {
                    "id": f"edge:contains:{brand['id']}:{node['id']}",
                    "source": brand["id"],
                    "target": node["id"],
                    "relation_type": "contains",
                    "metadata": {"source": OFFICIAL_SOURCE},
                }
            )

    bundle["nodes"].extend(new_nodes)
    bundle["edges"].extend(new_edges)
    return bundle


def main() -> int:
    manifest = build_manifest()
    copied = copy_web_assets()
    write_web_stylesheet()
    bundle = build_bundle(copied, manifest)

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    OUTPUT_BUNDLE.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"manifest: {manifest['file_count']} files, {manifest['total_bytes']} bytes")
    print(f"web assets: {len(copied)}")
    print(f"bundle: {len(bundle['nodes'])} nodes, {len(bundle['edges'])} edges")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")
    print(f"wrote {OUTPUT_BUNDLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
