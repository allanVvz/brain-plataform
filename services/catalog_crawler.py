from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if len(text) >= 3:
            self.parts.append(text)


def fetch_shopify_json_tool(base_url: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Tool: Busca produtos diretamente do endpoint padrao do Shopify."""
    parsed = urlparse(base_url)
    shopify_url = f"{parsed.scheme}://{parsed.netloc}/products.json"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(shopify_url, headers={"User-Agent": "AI-Brain-KB-Crawler/0.1"})
            if response.status_code == 200:
                data = response.json()
                products = data.get("products", [])
                candidates = []
                for p in products:
                    # Extrai variantes de preco
                    variants = p.get("variants", [])
                    prices = sorted(list({v.get("price") for v in variants if v.get("price")}))
                    
                    # Extrai cores/opcoes se existirem
                    options = p.get("options", [])
                    colors = []
                    for opt in options:
                        if opt.get("name", "").lower() in ["cor", "cores", "color", "colors"]:
                            colors = opt.get("values", [])

                    candidates.append({
                        "title": p.get("title"),
                        "description": p.get("body_html"),
                        "prices": prices,
                        "colors": colors,
                        "handle": p.get("handle"),
                        "source": "shopify_json"
                    })
                return candidates
    except Exception:
        pass
    return []


def _extract_visible_text(html: str) -> list[str]:
    parser = _TextExtractor()
    parser.feed(html)
    seen: set[str] = set()
    chunks: list[str] = []
    for part in parser.parts:
        if part.lower() in seen:
            continue
        seen.add(part.lower())
        chunks.append(part)
    return chunks[:180]


def _extract_json_ld_products(html: str) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            graph = node.get("@graph") if isinstance(node, dict) else None
            if isinstance(graph, list):
                nodes.extend(graph)
                continue
            if not isinstance(node, dict):
                continue
            kind = node.get("@type")
            if isinstance(kind, list):
                is_product = "Product" in kind
            else:
                is_product = kind == "Product"
            if not is_product:
                continue
            offer = node.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            products.append(
                {
                    "title": node.get("name"),
                    "description": node.get("description"),
                    "price": offer.get("price") if isinstance(offer, dict) else None,
                    "currency": offer.get("priceCurrency") if isinstance(offer, dict) else None,
                    "source": "json_ld",
                }
            )
    return [p for p in products if p.get("title")]


def _extract_text_product_candidates(text_blocks: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    product_re = re.compile(r"\b(kit|modal|tricot|cropped|blusa|conjunto|cal[cç]a|vestido|body)\b", re.I)
    price_re = re.compile(r"(?:R\$\s*)?\d{1,3}(?:[.,]\d{2})")
    color_re = re.compile(
        r"\b(preto|branco|off white|bege|nude|vermelho|vinho|azul|marinho|verde|rosa|cinza|caramelo|chocolate)\b",
        re.I,
    )
    for block in text_blocks:
        if not product_re.search(block):
            continue
        prices = sorted(set(price_re.findall(block)))
        colors = sorted({m.group(0).lower() for m in color_re.finditer(block)})
        candidates.append(
            {
                "title": block[:120],
                "prices": prices,
                "colors": colors,
                "source": "visible_text",
            }
        )
        if len(candidates) >= 20:
            break
    return candidates


def _score(products: list[dict[str, Any]], text_blocks: list[str], warnings: list[str]) -> float:
    score = 0.2
    if text_blocks:
        score += 0.15
    if products:
        score += 0.2
    if any(p.get("price") or p.get("prices") for p in products):
        score += 0.15
    if any(p.get("colors") for p in products):
        score += 0.1
    if warnings:
        score -= min(0.25, len(warnings) * 0.08)
    return max(0.05, min(0.82, round(score, 2)))


def crawl_catalog_url_tool(url: str, *, timeout: float = 12.0) -> dict[str, Any]:
    """Tool principal de crawling que coordena extratores especificos."""
    stages = [
        {"key": "fetch", "label": "captura bruta da URL", "status": "pending"},
        {"key": "shopify", "label": "detecçao de API Shopify", "status": "pending"},
        {"key": "parse", "label": "parsing HTML/texto", "status": "pending"},
        {"key": "extract", "label": "candidatos de produtos", "status": "pending"},
        {"key": "score", "label": "score de confianca", "status": "pending"},
    ]
    warnings: list[str] = []
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL invalida para crawler")

    html = ""
    status_code = None
    final_url = url
    products = []

    # 1. Tenta Tool Shopify primeiro (mais confiavel)
    shopify_candidates = fetch_shopify_json_tool(url, timeout=timeout)
    if shopify_candidates:
        products.extend(shopify_candidates)
        stages[1]["status"] = "done"
    else:
        stages[1]["status"] = "not_found"

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "AI-Brain-KB-Crawler/0.1"})
            status_code = response.status_code
            final_url = str(response.url)
            response.raise_for_status()
            html = response.text
            stages[0]["status"] = "done"
    except Exception as exc:
        stages[0]["status"] = "error"
        if not products: # So falha se o shopify tambem nao trouxe nada
            warnings.append(f"Falha ao capturar URL: {exc}")
        confidence = _score([], [], warnings)
        stages[4]["status"] = "done"
        return {
            "url": url,
            "final_url": final_url,
            "status_code": status_code,
            "confidence": confidence,
            "confidence_label": "baixa",
            "raw_text_preview": "",
            "text_blocks": [],
            "product_candidates": [],
            "warnings": warnings,
            "stages": stages,
        }

    text_blocks = _extract_visible_text(html)
    stages[2]["status"] = "done" if text_blocks else "warning"
    if not text_blocks:
        warnings.append("Nenhum texto visivel relevante foi extraido; o site pode depender de JavaScript ou imagens.")

    products.extend(_extract_json_ld_products(html))
    products.extend(_extract_text_product_candidates(text_blocks))
    stages[3]["status"] = "done" if products else "warning"
    if not products:
        warnings.append("Nenhum produto estruturado foi encontrado automaticamente.")

    confidence = _score(products, text_blocks, warnings) if not shopify_candidates else 0.85
    stages[4]["status"] = "done"
    label = "alta" if confidence >= 0.72 else "media" if confidence >= 0.45 else "baixa"

    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "confidence": confidence,
        "confidence_label": label,
        "raw_text_preview": "\n".join(text_blocks[:40])[:5000],
        "text_blocks": text_blocks[:80],
        "product_candidates": products[:30],
        "warnings": warnings,
        "stages": stages,
        "validation_policy": "raw_capture_only_human_validation_required",
        "source_note": "Crawler heuristico: candidatos podem estar incompletos, duplicados ou faltar dados renderizados por JavaScript/imagem.",
        "absolute_source": urljoin(final_url, "/"),
    }


def crawl_catalog_url(url: str, *, timeout: float = 12.0) -> dict[str, Any]:
    """Wrapper para manter compatibilidade com chamadas existentes."""
    return crawl_catalog_url_tool(url, timeout=timeout)
