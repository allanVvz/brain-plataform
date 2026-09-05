import mimetypes

from fastapi import APIRouter, HTTPException, Query, Response
from services import published_site_blocks, site_blocks, supabase_client

router = APIRouter(tags=["menu"])


def _page(slug):
    try:
        return published_site_blocks.public_payload(slug)
    except (published_site_blocks.PageNotFound, site_blocks.SiteBlockError):
        raise HTTPException(404, "Public page not found") from None


@router.get("/api/menu/{page_slug}/blocks")
def blocks(page_slug: str, response: Response):
    payload = _page(page_slug)
    # Revalidate on every read: activation cannot leave stale commercial media.
    response.headers["Cache-Control"] = "no-cache, must-revalidate"
    response.headers["ETag"] = '"' + payload["publication"]["checksum"] + '"'
    return payload


@router.get("/api/menu/{page_slug}/media/{asset_node_id}")
def media(page_slug: str, asset_node_id: str, publication: str = Query(...)):
    payload = _page(page_slug)
    if str(payload["publication"]["id"]) != publication:
        raise HTTPException(404, "Media publication expired")
    asset = published_site_blocks.media_references(payload).get(asset_node_id)
    if not asset or not asset.get("bucket") or not asset.get("path"):
        raise HTTPException(404, "Media not found")
    mime = mimetypes.guess_type(asset["path"])[0] or "application/octet-stream"
    if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}:
        raise HTTPException(404, "Media not found")
    try:
        content = supabase_client.download_from_storage(asset["bucket"], asset["path"])
    except Exception:
        raise HTTPException(404, "Media unavailable") from None
    return Response(content, media_type=mime, headers={"Cache-Control": "no-cache, must-revalidate",
                    "X-Content-Type-Options": "nosniff"})
