"""Local launcher: load env.qa.yaml into os.environ, then run uvicorn against api.main."""
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / "env.qa.yaml"
API_DIR = REPO_ROOT / "api"

if not ENV_FILE.exists():
    sys.exit(f"env file not found: {ENV_FILE}")

with ENV_FILE.open("r", encoding="utf-8") as fh:
    config = yaml.safe_load(fh) or {}
for key, value in config.items():
    if value is None:
        continue
    os.environ[str(key)] = str(value)

os.environ.setdefault("RUN_EMBEDDED_WORKERS", "false")
os.environ.setdefault("AI_BRAIN_LOCAL_DEV", "true")

sys.path.insert(0, str(API_DIR))
os.chdir(API_DIR)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8001")),
        reload=True,
        reload_dirs=[str(API_DIR)],
        log_level="info",
    )
