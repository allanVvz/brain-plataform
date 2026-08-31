from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from brain_contracts import BuildHealth, CanonicalInboundEnvelope, InternalPrincipalClaims


def test_internal_claims_are_strict_and_immutable():
    now = datetime.now(UTC)
    claims = InternalPrincipalClaims(
        subject=uuid4(), role="service", persona_ids=(), service="gateway",
        issued_at=now, expires_at=now + timedelta(seconds=60), nonce="n",
    )
    assert claims.contract_version == "1.0"
    with pytest.raises(ValidationError):
        InternalPrincipalClaims(**claims.model_dump(), injected=True)


def test_health_requires_full_source_sha():
    with pytest.raises(ValidationError):
        BuildHealth(status="ready", service="runtime", source_sha="short",
                    build_digest="sha256:test", schema_version=130,
                    required_schema_version=130)


def test_inbound_v2_is_normalized_to_canonical_v3_identity():
    envelope = CanonicalInboundEnvelope(
        contract_version="2", inbound_id="inbound-1", correlation_id="correlation-1",
        persona_id=uuid4(), persona_slug="fixture", lead_ref="1", channel_binding_id=uuid4(),
        provider="internal_validator", received_at=datetime.now(UTC), message_type="text",
        content={"text": "oi"},
    )
    assert envelope.contract_version == "2"
    assert envelope.canonical_inbound_id == "inbound-1"
