from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


Checksum = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class DraftContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftMutationSource(DraftContractModel):
    surface: Literal["graph", "kb", "messages", "api", "import"]
    response_message_id: str | None = Field(default=None, min_length=1)
    source_ref: str | None = Field(default=None, min_length=1)


class GraphBundleDraftNode(DraftContractModel):
    id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    status: str = Field(default="pending_validation", min_length=1)
    tags: list[str] = Field(default_factory=list)
    projection_node_id: str | None = Field(default=None, min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class GraphBundleDraftEdge(DraftContractModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation_type: str = Field(default="contains", min_length=1)
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateGraphBundleDraftBody(DraftContractModel):
    persona_slug: str = Field(min_length=1, max_length=128)
    expected_active_checksum: Checksum
    reuse_open: bool = True
    reason: str = Field(min_length=3, max_length=1000)
    source: DraftMutationSource
    idempotency_key: str = Field(min_length=8, max_length=200)


class UpdateNodeOperation(DraftContractModel):
    op: Literal["update_node"]
    node_id: str = Field(min_length=1)
    patch: dict[str, Any]

    @field_validator("patch")
    @classmethod
    def validate_patch(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("update_node patch cannot be empty")
        forbidden = {"id", "projection_node_id", "persona", "persona_id", "persona_slug"}
        invalid = sorted(key for key in value if key in forbidden)
        if invalid:
            raise ValueError(f"immutable node fields: {','.join(invalid)}")
        allowed = {"title", "summary", "status", "tags"}
        invalid = sorted(
            key for key in value
            if key not in allowed and not key.startswith("data.")
        )
        if invalid:
            raise ValueError(f"unsupported node patch fields: {','.join(invalid)}")
        return value


class AddNodeOperation(DraftContractModel):
    op: Literal["add_node"]
    node: GraphBundleDraftNode


class ArchiveNodeOperation(DraftContractModel):
    op: Literal["archive_node"]
    node_id: str = Field(min_length=1)


class AddEdgeOperation(DraftContractModel):
    op: Literal["add_edge"]
    edge: GraphBundleDraftEdge


class RevokeEdgeOperation(DraftContractModel):
    op: Literal["revoke_edge"]
    edge_id: str = Field(min_length=1)


class ApproveFaqOperation(DraftContractModel):
    op: Literal["approve_faq"]
    node_id: str = Field(min_length=1)


class RejectFaqOperation(DraftContractModel):
    op: Literal["reject_faq"]
    node_id: str = Field(min_length=1)


class AddFaqProposalOperation(DraftContractModel):
    op: Literal["add_faq_proposal"]
    node_id: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    question: str = Field(min_length=2)
    answer: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    source_node_type: str = Field(min_length=1)
    branch_path: list[str] = Field(min_length=2)
    question_aliases: list[str] = Field(default_factory=list)
    generator: str = Field(min_length=1)
    generation_batch_id: str = Field(min_length=1)


GraphBundleDraftOperation = Annotated[
    Union[
        UpdateNodeOperation,
        AddNodeOperation,
        ArchiveNodeOperation,
        AddEdgeOperation,
        RevokeEdgeOperation,
        ApproveFaqOperation,
        RejectFaqOperation,
        AddFaqProposalOperation,
    ],
    Field(discriminator="op"),
]


class PatchGraphBundleDraftBody(DraftContractModel):
    expected_revision: int = Field(ge=1)
    expected_draft_checksum: Checksum
    reason: str = Field(min_length=3, max_length=1000)
    source: DraftMutationSource
    operations: list[GraphBundleDraftOperation] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)


class SealGraphBundleDraftBody(DraftContractModel):
    expected_revision: int = Field(ge=1)
    expected_draft_checksum: Checksum
    idempotency_key: str = Field(min_length=8, max_length=200)


class FaqImpactBody(DraftContractModel):
    expected_revision: int = Field(ge=1)
    expected_draft_checksum: Checksum
    changed_node_ids: list[str] = Field(min_length=1, max_length=100)


class StageGraphBundleDraftBody(SealGraphBundleDraftBody):
    plan_ref: str = Field(min_length=1)
    validation_ref: str = Field(min_length=1)
    approved_runtime_checksum: Checksum


class ActivateGraphPublicationBody(DraftContractModel):
    expected_active_publication_id: str = Field(min_length=1)
    expected_active_checksum: Checksum
    approved_draft_checksum: Checksum
    approved_runtime_checksum: Checksum
    validation_ref: str = Field(min_length=1)
    confirmation: Literal[True]
    reason: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=200)


class PublishGraphBundleDraftBody(DraftContractModel):
    expected_revision: int = Field(ge=1)
    expected_draft_checksum: Checksum
    plan_ref: str = Field(min_length=1)
    validation_ref: str = Field(min_length=1)
    approved_runtime_checksum: Checksum
    confirmation: Literal[True]
    reason: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=200)
