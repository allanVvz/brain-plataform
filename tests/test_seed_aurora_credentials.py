from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.seed_aurora import _write_new_credential


def test_aurora_credential_file_is_created_once_without_overwrite(tmp_path):
    output = tmp_path / "private" / "aurora-credential.txt"
    result = _write_new_credential(str(output), "temporary-secret")

    assert result == output
    assert "temporary-secret" in output.read_text(encoding="utf-8")
    if sys.platform != "win32":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600

    with pytest.raises(FileExistsError):
        _write_new_credential(str(output), "replacement-secret")
    assert "replacement-secret" not in output.read_text(encoding="utf-8")
