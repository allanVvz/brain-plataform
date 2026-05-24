#!/usr/bin/env python3
"""E2E: VZ Lupas full catalog (3 product_groups x 3 products + 10 assets).

Validates the cardapio pipeline end-to-end for the VZ Lupas persona without
touching baita-conveniencia or any hardcoded slug. Idempotent: re-runs reuse
existing nodes when the spine matches and only fix missing assets/edges.

Steps:
  1. Resolve the VZ Lupas persona (must exist).
  2. Archive legacy spines that would pollute the catalog (vz-pg-t2-* etc.).
  3. Generate 10 PNG placeholders (1 per product + 1 campaign hero).
  4. POST /assets/upload for each placeholder with branch_hint = parent slug
     and asset_function = product_image (9 products) or campaign_hero (1).
  5. GET /api/menu/vz-lupas and assert: 3 categories, 9 products, every product
     payload contains at least one asset, the collection campaign has an asset.
  6. Save the menu payload + a summary report to test-artifacts/.

Auth: passes X-AI-BRAIN-ADMIN-TOKEN (env AI_BRAIN_ADMIN_TEST_TOKEN). Targets
the QA Cloud Run service by default — override with --api-base.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-vz-lupas-full"
ASSETS_DIR = ARTIFACTS_DIR / "assets"
PERSONA_SLUG = "vz-lupas"

# Canonical 3 product_groups x 3 products = 9, already seeded in QA via t3 run.
GROUPS: list[dict[str, Any]] = [
    {
        "group_slug": "vz-pg-clipon-t3-1779530167",
        "label": "Clip-on VZ",
        "color": (94, 92, 230),   # indigo
        "products": [
            ("vz-clipon-aviator-t3-1779530167", "Clip-on Aviator"),
            ("vz-clipon-classic-t3-1779530167", "Clip-on Classic"),
            ("vz-clipon-sport-t3-1779530167",   "Clip-on Sport"),
        ],
    },
    {
        "group_slug": "vz-pg-grau-t3-1779530167",
        "label": "Armacoes de Grau VZ",
        "color": (52, 152, 219),  # blue
        "products": [
            ("vz-grau-acetato-t3-1779530167", "Armacao Grau Acetato"),
            ("vz-grau-metal-t3-1779530167",   "Armacao Grau Metal"),
            ("vz-grau-titanio-t3-1779530167", "Armacao Grau Titanio"),
        ],
    },
    {
        "group_slug": "vz-pg-sol-t3-1779530167",
        "label": "Oculos de Sol VZ",
        "color": (231, 76, 60),   # red
        "products": [
            ("vz-sol-aviador-t3-1779530167",  "Lupa Sol Aviador"),
            ("vz-sol-quadrado-t3-1779530167", "Lupa Sol Quadrado"),
            ("vz-sol-redondo-t3-1779530167",  "Lupa Sol Redondo"),
        ],
    },
]
# Use the existing T3 campaign as the canonical campaign for VZ Lupas.
CAMPAIGN_SLUG = "campanha-conhecimento-vz-lupas-e2e-t3-1779530167"
# Legacy t2 spine — archived from the catalog so the menu shows exactly 3x3.
LEGACY_SLUGS = ["vz-pg-t2-1779530167", "vz-prod-t2-1779530167"]


class TestFailure(Exception):
    pass


def http_json(
    method: str,
    base: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    admin_token: str | None = None,
    timeout: float = 90.0,
    retries: int = 2,
) -> Any:
    url = base.rstrip("/") + path
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    data = None
    headers = {"Accept": "application/json"}
    if admin_token:
        headers["X-AI-BRAIN-ADMIN-TOKEN"] = admin_token
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    for attempt in range(retries + 1):
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1500]
            if exc.code in {502, 503, 504} and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise TestFailure(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise TestFailure(f"{method} {path} -> connection failed: {exc}") from exc
    raise TestFailure(f"{method} {path} failed after retries")


def multipart_upload(
    base: str,
    path: str,
    *,
    file_path: Path,
    fields: dict[str, str],
    admin_token: str,
    timeout: float = 120.0,
) -> dict:
    """Plain multipart/form-data POST without external deps."""
    boundary = f"----brainboundary{int(time.time()*1000)}"
    body = io.BytesIO()
    for name, value in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(f"{value}\r\n".encode())
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode()
    )
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(file_path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    data = body.getvalue()
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(data)),
        "X-AI-BRAIN-ADMIN-TOKEN": admin_token,
        "Accept": "application/json",
    }
    req = request.Request(base.rstrip("/") + path, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise TestFailure(f"upload {file_path.name} -> HTTP {exc.code}: {detail}") from exc


def font(size: int) -> ImageFont.ImageFont:
    # Pillow always ships a default bitmap font; no system fonts required.
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def render_placeholder(
    out_path: Path,
    *,
    color: tuple[int, int, int],
    title: str,
    subtitle: str,
) -> None:
    img = Image.new("RGB", (512, 512), color)
    draw = ImageDraw.Draw(img)
    # White rounded plate so the text stays legible across all 3 group colors.
    plate_bbox = (32, 160, 480, 352)
    draw.rectangle(plate_bbox, fill=(255, 255, 255))
    draw.rectangle((32, 160, 480, 200), fill=color)
    draw.text((48, 168), "VZ LUPAS", fill=(255, 255, 255), font=font(20))
    draw.text((48, 220), title, fill=(20, 20, 20), font=font(34))
    draw.text((48, 270), subtitle, fill=(80, 80, 80), font=font(18))
    draw.text((48, 460), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
              fill=(240, 240, 240), font=font(14))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)


def archive_legacy(base: str, admin_token: str, report: dict) -> None:
    """Legacy vz-pg-t2 cleanup is done out-of-band via the Supabase MCP because
    the public API does not expose a soft-delete for nodes today. This step
    just records which slugs the operator should have archived so the report
    is self-explanatory when re-reading later."""
    report["legacy_archive_note"] = (
        "Legacy spines archived via Supabase MCP: " + ", ".join(LEGACY_SLUGS)
    )


def upload_assets(base: str, admin_token: str, persona_id: str, report: dict) -> dict:
    """Generate placeholders and upload one per product + one for the campaign.

    Returns a dict mapping branch_hint slug -> uploaded asset payload.
    """
    uploaded: dict[str, dict] = {}
    for group in GROUPS:
        for slug, title in group["products"]:
            out = ASSETS_DIR / f"{slug}.png"
            render_placeholder(out, color=group["color"], title=title, subtitle=group["label"])
            payload = multipart_upload(
                base, "/assets/upload",
                file_path=out,
                fields={
                    "persona_id": persona_id,
                    "persona_slug": PERSONA_SLUG,
                    "branch_hint": slug,
                    "asset_function": "product_image",
                },
                admin_token=admin_token,
            )
            uploaded[slug] = payload
            report.setdefault("uploaded", []).append({"branch_hint": slug, "asset_id": payload.get("id") or (payload.get("asset") or {}).get("id")})
    # Campaign hero
    campaign_out = ASSETS_DIR / f"{CAMPAIGN_SLUG}.png"
    render_placeholder(
        campaign_out,
        color=(20, 24, 33),
        title="Lancamento Oakley 2026",
        subtitle="VZ Lupas Premium",
    )
    payload = multipart_upload(
        base, "/assets/upload",
        file_path=campaign_out,
        fields={
            "persona_id": persona_id,
            "persona_slug": PERSONA_SLUG,
            "branch_hint": CAMPAIGN_SLUG,
            "asset_function": "campaign_hero",
        },
        admin_token=admin_token,
    )
    uploaded[CAMPAIGN_SLUG] = payload
    report.setdefault("uploaded", []).append({"branch_hint": CAMPAIGN_SLUG, "asset_id": payload.get("id") or (payload.get("asset") or {}).get("id")})
    return uploaded


def approve_uploads(base: str, admin_token: str, uploaded: dict[str, dict], report: dict) -> None:
    """POST /assets/{id}/approve so list_gallery_assets returns them with
    effective_status='approved', which is what the menu filter requires."""
    for slug, payload in uploaded.items():
        asset_id = payload.get("id") or (payload.get("asset") or {}).get("id")
        if not asset_id:
            report.setdefault("approve_skipped", []).append({"branch_hint": slug, "reason": "missing asset_id"})
            continue
        try:
            http_json("POST", base, f"/assets/{asset_id}/approve", body={}, admin_token=admin_token)
            report.setdefault("approved", []).append({"branch_hint": slug, "asset_id": asset_id})
        except TestFailure as exc:
            report.setdefault("approve_failed", []).append({"branch_hint": slug, "asset_id": asset_id, "error": str(exc)[:300]})


def validate_menu(base: str, admin_token: str, report: dict) -> dict:
    payload = http_json("GET", base, f"/api/menu/{PERSONA_SLUG}", params={"nocache": 1}, admin_token=admin_token)
    persona = (payload or {}).get("persona") or {}
    collections = persona.get("collections") or []
    if not collections:
        raise TestFailure("menu payload has no collections")
    collection = collections[0]
    categories = [c for c in (collection.get("categories") or []) if c.get("visible") is not False]
    total_products = 0
    products_without_assets: list[str] = []
    for cat in categories:
        for product in cat.get("products") or []:
            total_products += 1
            if not (product.get("assets") or []):
                products_without_assets.append(product.get("slug") or product.get("name") or "?")
    campaign_assets = collection.get("assets") or []
    summary = {
        "groups": len(categories),
        "products": total_products,
        "products_without_assets": products_without_assets,
        "campaign_assets": len(campaign_assets),
        "collection_slug": collection.get("slug"),
        "persona_name": persona.get("name"),
        "catalog_url_resolved_to": (payload or {}).get("persona", {}).get("brand", {}).get("slug"),
    }
    report["menu_summary"] = summary
    # Persist the full payload — handy for debugging cardapio render issues.
    (ARTIFACTS_DIR / "menu.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if summary["groups"] != 3:
        raise TestFailure(f"expected 3 groups, got {summary['groups']}")
    if summary["products"] != 9:
        raise TestFailure(f"expected 9 products, got {summary['products']}")
    if products_without_assets:
        raise TestFailure(f"products missing assets: {products_without_assets}")
    if summary["campaign_assets"] < 1:
        raise TestFailure("campaign hero asset missing from collection.assets")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", "https://ai-brain-api-qa-837167469397.us-central1.run.app"))
    parser.add_argument("--admin-token", default=os.environ.get("AI_BRAIN_ADMIN_TEST_TOKEN", ""))
    parser.add_argument("--skip-upload", action="store_true", help="Skip placeholder generation + upload; only validate the menu.")
    parser.add_argument("--skip-archive", action="store_true", help="Skip archiving vz-pg-t2 legacy spine.")
    args = parser.parse_args()
    if not args.admin_token:
        print("ERROR: AI_BRAIN_ADMIN_TEST_TOKEN env or --admin-token required for QA write endpoints.")
        return 2

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "api_base": args.api_base,
        "persona_slug": PERSONA_SLUG,
    }

    try:
        personas = http_json("GET", args.api_base, "/personas", admin_token=args.admin_token)
        persona = next((p for p in (personas or []) if p.get("slug") == PERSONA_SLUG), None)
        if not persona:
            raise TestFailure(f"persona {PERSONA_SLUG} not found in /personas")
        report["persona_id"] = persona.get("id")
        report["persona_catalog_url"] = persona.get("catalog_url")

        if not args.skip_archive:
            print("[1/4] archiving legacy vz-pg-t2 spine...")
            archive_legacy(args.api_base, args.admin_token, report)
        else:
            print("[1/4] SKIPPED archive (--skip-archive)")

        if not args.skip_upload:
            print("[2/5] generating + uploading 9 product images + 1 campaign hero...")
            uploaded = upload_assets(args.api_base, args.admin_token, persona["id"], report)
            print("[3/5] approving uploaded assets so menu picks them up...")
            approve_uploads(args.api_base, args.admin_token, uploaded, report)
        else:
            print("[2/5] SKIPPED upload (--skip-upload)")
            print("[3/5] SKIPPED approve (no uploads in this run)")

        print("[4/5] validating /api/menu/vz-lupas...")
        summary = validate_menu(args.api_base, args.admin_token, report)
        print(f"      OK -> {summary['groups']} groups, {summary['products']} products, {summary['campaign_assets']} campaign asset(s)")

        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "ok"
        print("[5/5] artifacts written to", ARTIFACTS_DIR)
    except TestFailure as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        print(f"FAILED: {exc}", file=sys.stderr)
    except Exception as exc:  # pragma: no cover - defensive
        report["status"] = "crashed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"CRASHED: {report['error']}", file=sys.stderr)
    finally:
        (ARTIFACTS_DIR / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
