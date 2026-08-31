"""Compatibility alias for the control-plane database repository."""

from __future__ import annotations

import sys

from repositories import control_plane as _repository


sys.modules[__name__] = _repository
