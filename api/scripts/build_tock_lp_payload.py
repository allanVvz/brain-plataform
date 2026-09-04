"""Build the Tock Fatal public landing payload from the graph bundle.

Reads the approved bundle, resolves the ``landing_page`` block template scoped
to one commercial branch, and writes the JSON the public renderer consumes.

This script only reads. It does not publish, does not touch the runtime, and
does not change any publication checksum.

    python api/scripts/build_tock_lp_payload.py
    python api/scripts/build_tock_lp_payload.py --scope audience:tock-reseller
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "api"))

from services import site_blocks  # noqa: E402

BUNDLE = REPO_ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v12-model-owned.json"
OUT_DIR = REPO_ROOT / "data/public_sites/tock-fatal"

# The public contact number, confirmed by the operator on 2026-09-04. This is
# personas.config.public_site.whatsapp_phone -- the CTA phone -- and never the
# Meta whatsapp_phone_number_id used for operational routing.
WHATSAPP_PHONE = "5551992623375"

SCOPES = {
    "audience:tock-retail": {
        "out": "landing-varejo.json",
        "site_slug": "tock-fatal",
        "site_name": "Tock Fatal",
        "message": "Oi! Vim pelo site da Tock Fatal e quero ver as peças.",
    },
    "audience:tock-reseller": {
        "out": "landing-atacado.json",
        "site_slug": "tock-fatal-atacado",
        "site_name": "Tock Fatal Atacado",
        "message": "Oi! Vim pelo site e quero comprar para revender.",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default="audience:tock-retail", choices=sorted(SCOPES))
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    config = SCOPES[args.scope]
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))

    payload = site_blocks.resolve_blocks(
        bundle,
        template_key="landing_page",
        scope=args.scope,
        site={
            "site_slug": config["site_slug"],
            "site_name": config["site_name"],
            "format_key": "landing_page",
            "whatsapp_phone": WHATSAPP_PHONE,
            "whatsapp_message_template": config["message"],
        },
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    target = args.out_dir / config["out"]
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    groups = next(
        (b["data"]["groups"] for b in payload["blocks"] if b["kind"] == "group_index"),
        [],
    )
    price = next(
        (b["data"] for b in payload["blocks"] if b["kind"] == "price_range"), {}
    )
    print(f"wrote {target.relative_to(REPO_ROOT)}")
    print(f"  scope        {args.scope}")
    print(f"  blocks       {[b['id'] for b in payload['blocks']]}")
    print(f"  groups       {len(groups)}")
    print(f"  offers       {price.get('offer_count')}")
    if price.get("min_cents") is not None:
        print(f"  price range  R$ {price['min_cents']/100:.2f} - R$ {price['max_cents']/100:.2f}")
    for group in groups:
        low = group["price_from_cents"]
        low_text = f"a partir de R$ {low/100:.2f}" if low else "sem preço"
        print(f"    - {group['title'][:44]:<44} {group['product_count']:>3} peças  {low_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
