"""Package GraphBundle local media without escaping the repository root."""
from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def media_paths(bundle_path: Path) -> list[Path]:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    paths: list[Path] = []
    for node in bundle.get("nodes") or []:
        value = str((node.get("data") or {}).get("local_evidence_path") or "")
        if not value:
            continue
        candidate = (ROOT / value).resolve()
        candidate.relative_to(ROOT.resolve())
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        paths.append(candidate)
    return sorted(set(paths))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("output")
    args = parser.parse_args()
    bundle_path = (ROOT / args.bundle).resolve()
    bundle_path.relative_to(ROOT.resolve())
    output = Path(args.output).resolve()
    paths = media_paths(bundle_path)
    with tarfile.open(output, "w:gz") as archive:
        for path in paths:
            archive.add(path, arcname=path.relative_to(ROOT).as_posix(), recursive=False)
    print(json.dumps({"archive": str(output), "asset_count": len(paths)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
