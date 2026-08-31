"""Run every deployable app's tests in an isolated import namespace."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS = {
    "gateway": ROOT / "apps/gateway",
    "control-plane": ROOT / "apps/control-plane/api",
    "conversation-runtime": ROOT / "apps/conversation-runtime/api",
    "transport": ROOT / "apps/transport/api",
}


def main() -> int:
    packages = [
        str(ROOT / "packages/brain-contracts"),
        str(ROOT / "packages/brain-shared"),
    ]
    for name, directory in APPS.items():
        tests = directory / "tests"
        if not tests.is_dir():
            raise RuntimeError(f"{name} has no isolated tests")
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(packages + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env.setdefault("SUPABASE_OFFLINE", "true")
        env.setdefault("KNOWLEDGE_TAXONOMY_OFFLINE", "true")
        print(f"== {name} ==", flush=True)
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=directory, env=env)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
