from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "microservices" / "render-monorepo-release-manifest.py"
spec = importlib.util.spec_from_file_location("render_monorepo_release_manifest", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_every_service_requires_the_manifest_schema_version() -> None:
    digest = "sha256:" + "a" * 64
    manifest = module.render(
        source_sha="b" * 40,
        schema_version=139,
        digests={name: digest for name in module.SERVICES},
    )

    assert manifest["schema_version"] == 139
    assert {
        service["required_schema_version"]
        for service in manifest["services"].values()
    } == {139}
