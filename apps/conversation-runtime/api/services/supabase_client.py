"""Compatibility alias for the conversation-runtime database repository."""

from __future__ import annotations

import sys

from repositories import runtime as _repository


sys.modules[__name__] = _repository
