from __future__ import annotations

import os
from functools import lru_cache

import certifi


@lru_cache(maxsize=1)
def get_ca_bundle_path() -> str:
    custom = (os.environ.get("AI_BRAIN_CA_BUNDLE") or "").strip()
    return custom or certifi.where()


def configure_trust_store() -> str:
    bundle = get_ca_bundle_path()
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    os.environ.setdefault("CURL_CA_BUNDLE", bundle)
    return bundle

