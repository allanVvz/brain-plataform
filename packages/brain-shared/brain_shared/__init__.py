"""Pure shared primitives; domain code is deliberately excluded."""

from .internal_auth import sign_principal, verify_principal
from .http import internal_url

__all__ = ["sign_principal", "verify_principal", "internal_url"]
