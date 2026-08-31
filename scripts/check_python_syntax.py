from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    checked = 0
    candidates = list((ROOT / "api").rglob("*.py"))
    candidates.extend((ROOT / "apps").rglob("*.py"))
    candidates.extend((ROOT / "packages").rglob("*.py"))
    candidates.extend((ROOT / "tests").glob("test_*.py"))
    for path in candidates:
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        source = path.read_text(encoding="utf-8-sig")
        compile(source, str(path.relative_to(ROOT)), "exec")
        checked += 1
    print(f"python syntax ok ({checked} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
