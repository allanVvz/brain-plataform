"""Strict contracts shared by Brain and persona n8n workflows."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationRoute(StrEnum):
    SDR = "SDR"
    CLOSER = "CLOSER"
    HUMAN = "HUMAN"


class ConversationJourneyState(StrEnum):
    COLLECTING = "collecting"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUALIFIED_CONFIRMED = "qualified_confirmed"
    HANDED_OFF = "handed_off"
    CONVERTED = "converted"
    CLOSED = "closed"


class ConversationOperationalMode(StrEnum):
    COLLECTION = "collection"
    CONFIRMATION = "confirmation"
    POST_QUALIFICATION_SUPPORT = "post_qualification_support"


class CartAction(StrEnum):
    NONE = "none"
    ADD_ITEM = "add_item"
    CHANGE_QUANTITY = "change_quantity"
    REMOVE_ITEM = "remove_item"
    SHOW_TOTAL = "show_total"
    CONFIRM_ORDER = "confirm_order"
    CANCEL_ORDER = "cancel_order"


class ContextCard(StrictModel):
    """Immutable knowledge snapshot injected into one model turn.

    ``id`` is always the stable Graph JSON node id. Database projection UUIDs
    are deliberately kept as trace metadata and never become card identity.
    """

    id: str = Field(min_length=1)
    projection_node_id: str | None = None
    node_type: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    title: str = Field(min_length=1)
    rendered_content: str = Field(min_length=1)
    editable_content: str = ""
    content_checksum: str = Field(min_length=1)
    revision: int = Field(ge=1)
    graph_version: int = Field(ge=1)
    graph_checksum: str = Field(min_length=1)
    context_role: str
    position: int = Field(ge=0)
    selection_reason: dict[str, Any] = Field(default_factory=dict)
    path: list[str] = Field(default_factory=list)
    chunk_refs: list[str] = Field(default_factory=list)
    source: str = "pending_source"
    status: str = "approved"
    relations: list[dict[str, Any]] = Field(default_factory=list)
    technical_metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationFactStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    DECLINED = "declined"
    NEEDS_CONFIRMATION = "needs_confirmation"
    INVALID = "invalid"


class BranchAction(StrEnum):
    NONE = "none"
    KEEP = "keep"
    SELECT = "select"
    SWITCH = "switch"
    ADD = "add"


class ServiceOperationAction(StrEnum):
    ADD = "add"
    KEEP = "keep"
    DROP = "drop"


class ServiceOperation(StrictModel):
    """Graph-proved mutation of the active service set for one inbound."""

    action: ServiceOperationAction
    branch_anchor_node_id: str = Field(min_length=1)
    branch_path_checksum: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)
    evidence_type: str = Field(
        default="exact_catalog",
        pattern="^(exact_catalog|confirmed_candidate|explicit_change)$",
    )
    resolution_method: str = "exact_catalog"
    score: float | None = Field(default=None, ge=0, le=1)
    margin: float | None = Field(default=None, ge=0, le=1)


class ServiceObservation(StrictModel):
    """Non-authoritative service signal observed by the model."""

    branch_anchor_node_id: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)
    observed_intent: str = Field(
        default="mention",
        pattern="^(mention|select|add|switch|remove|question)$",
    )
    confidence: float = Field(default=0.0, ge=0, le=1)


class InteractionKind(StrEnum):
    CONTINUE_CURRENT = "continue_current"
    NEW_DEMAND = "new_demand"
    POST_COMPLETION_QUESTION = "post_completion_question"
    COURTESY_CLOSE = "courtesy_close"
    POST_SALE_OPERATION = "post_sale_operation"
    UNCLEAR = "unclear"


class JourneyAction(StrEnum):
    CONTINUE = "continue"
    OPEN = "open"
    NONE = "none"


class InteractionObservation(StrictModel):
    """Non-authoritative semantic observation reconciled by the backend."""

    kind: InteractionKind = InteractionKind.UNCLEAR
    evidence_span: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)


class SharedMemoryFact(StrictModel):
    key: str = Field(min_length=1)
    value: Any | None = None
    owner_node_id: str = Field(min_length=1)
    status: ConversationFactStatus
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str = "conversation_fact"
    journey_id: str | None = None
    recorded_at: str | None = None
    source_message_id: str | None = None
    reuse_policy: str = "historical_only"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SharedLeadMemory(StrictModel):
    """Agent-neutral, complete memory envelope for one persona-scoped lead."""

    profile_facts: list[SharedMemoryFact] = Field(default_factory=list)
    current_journey: dict[str, Any] | None = None
    historical_facts: list[SharedMemoryFact] = Field(default_factory=list)
    journey_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    pending_items: list[dict[str, Any]] = Field(default_factory=list)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    agent_activity: list[dict[str, Any]] = Field(default_factory=list)
    policy_version: str = "shared_lead_memory_v1"


class ExtractedFact(StrictModel):
    field_key: str = Field(min_length=1)
    value: Any | None = None
    status: ConversationFactStatus = ConversationFactStatus.KNOWN
    source_message_id: str | None = None
    owner_node_id: str = Field(min_length=1)
    evidence_span: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommercialClaim(StrictModel):
    # Claim taxonomy is graph-authored. Runtime proof checks the cited
    # published policy/chunks instead of rejecting valid domain-specific
    # knowledge because it is absent from a backend enum.
    claim_type: str = Field(min_length=1)
    value: dict[str, Any] = Field(default_factory=dict)
    evidence_node_ids: list[str] = Field(default_factory=list)
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class ConversationProposal(StrictModel):
    """One model suggestion that must be proved against the graph contract."""

    interaction_observation: InteractionObservation = Field(
        default_factory=InteractionObservation
    )
    branch_action: BranchAction = BranchAction.NONE
    branch_anchor_node_id: str | None = None
    branch_path_checksum: str | None = None
    branch_evidence_span: str = ""
    service_observations: list[ServiceObservation] = Field(default_factory=list)
    service_operations: list[ServiceOperation] = Field(default_factory=list)
    extracted_facts: list[ExtractedFact] = Field(default_factory=list)
    claims: list[CommercialClaim] = Field(default_factory=list)
    next_question_node_id: str | None = None
    cited_node_ids: list[str] = Field(default_factory=list)
    cited_chunk_ids: list[str] = Field(default_factory=list)
    reply: str = ""
    qualification_complete: bool = False
    handoff_requested: bool = False


class SemanticIntentKind(StrEnum):
    ANSWER_PENDING_FIELD = "answer_pending_field"
    COMMERCIAL_QUESTION = "commercial_question"
    SPONTANEOUS_INFO = "spontaneous_info"
    CORRECTION = "correction"
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"
    GREETING = "greeting"
    OBJECTION = "objection"
    PRODUCT_CHANGE = "product_change"
    AUDIENCE_CHANGE = "audience_change"
    RESUME = "resume"
    SMALL_TALK = "small_talk"
    UNCLEAR = "unclear"


class SemanticIntent(StrictModel):
    """One act the customer performed in this message.

    A message routinely carries several -- answering the pending question and
    asking a commercial one in the same breath -- so the contract is a list
    and the backend must serve every one of them.
    """

    kind: SemanticIntentKind
    evidence_span: str = Field(min_length=1)


class ConfirmationState(StrEnum):
    NONE = "none"
    AFFIRM = "affirm"
    REJECT = "reject"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"


class SemanticConfirmation(StrictModel):
    """Confirmation bound to something identifiable, not to positive words.

    ``target_ref`` is what the customer is agreeing WITH -- the pending
    confirmation the backend published this turn. A confirmation whose target
    does not match the pending one is not a confirmation of anything, which is
    what stops a bare "sim" from silently confirming an arbitrary claim.
    """

    state: ConfirmationState = ConfirmationState.NONE
    target_ref: str | None = None
    evidence_span: str = ""
    # For PARTIAL ("yes, but change X to Y"): what still has to change.
    correction_field_key: str | None = None
    correction_value: Any | None = None


class BranchSelectionAction(StrEnum):
    NONE = "none"
    KEEP = "keep"
    SELECT = "select"
    SWITCH = "switch"
    ADD = "add"
    DROP = "drop"


class SemanticBranchSelection(StrictModel):
    """Natural language normalized to a branch anchor published in the graph.

    The model does the normalizing ("é pra mim" -> the retail anchor); the
    backend only checks the anchor exists and the span is really in the
    message. No alias list in backend code.
    """

    action: BranchSelectionAction = BranchSelectionAction.NONE
    branch_anchor_node_id: str | None = None
    evidence_span: str = ""


class CustomerQuestionKind(StrEnum):
    AVAILABILITY = "availability"
    PRICE = "price"
    STOCK = "stock"
    POLICY = "policy"
    SCHEDULE = "schedule"
    DEADLINE = "deadline"
    PRODUCT_DETAIL = "product_detail"
    OTHER = "other"


class CustomerQuestion(StrictModel):
    """A question the customer asked that the turn owes an answer to.

    Kept separate from ``facts`` so an availability question is never absorbed
    as the raw value of whatever field happened to be pending.
    """

    kind: CustomerQuestionKind
    topic: str = Field(min_length=1)
    entity_node_ids: list[str] = Field(default_factory=list)
    evidence_span: str = Field(min_length=1)


class SemanticEntityKind(StrEnum):
    PRODUCT = "product"
    QUANTITY = "quantity"
    AUDIENCE = "audience"
    OTHER = "other"


class SemanticEntity(StrictModel):
    kind: SemanticEntityKind
    value: Any | None = None
    node_id: str | None = None
    evidence_span: str = Field(min_length=1)


class FactInvalidation(StrictModel):
    """A previously accepted fact this message makes untrue."""

    field_key: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)


class StateRelation(StrEnum):
    CONTINUE = "continue"
    NEW_DEMAND = "new_demand"
    CORRECTION = "correction"
    RESUME = "resume"
    POST_COMPLETION = "post_completion"
    UNCLEAR = "unclear"


class RecommendedNextAction(StrEnum):
    ASK_FIELD = "ask_field"
    ANSWER_QUESTION = "answer_question"
    CONFIRM = "confirm"
    HANDOFF = "handoff"
    CLARIFY = "clarify"
    CLOSE = "close"


class SemanticInterpretation(StrictModel):
    """The model's whole reading of one inbound, in one structured object.

    Replaces phrase-list interpretation in the backend. Every element carries
    the span of the customer's own words that supports it -- deliberately no
    numeric confidence anywhere, because a score is not an explanation and the
    backend must be able to re-check each claim against the literal message.
    """

    intents: list[SemanticIntent] = Field(default_factory=list)
    state_relation: StateRelation = StateRelation.UNCLEAR
    # Which pending field (if any) this message answers, by graph field key.
    answers_field_key: str | None = None
    confirmation: SemanticConfirmation = Field(default_factory=SemanticConfirmation)
    # A turn may open one branch, two at once ("é pra mim e também quero
    # revender"), or swap one for another. The literal resolver always emitted
    # a list of operations; the semantic reading has to be able to say the same
    # thing or it silently loses multi-branch conversations.
    branch_selections: list[SemanticBranchSelection] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    invalidated_facts: list[FactInvalidation] = Field(default_factory=list)
    entities: list[SemanticEntity] = Field(default_factory=list)
    questions: list[CustomerQuestion] = Field(default_factory=list)
    claims: list[CommercialClaim] = Field(default_factory=list)
    recommended_next_action: RecommendedNextAction = RecommendedNextAction.CLARIFY
    cited_node_ids: list[str] = Field(default_factory=list)
    cited_chunk_ids: list[str] = Field(default_factory=list)
    # Ephemeral reference to an existing graph question. This carries the
    # model's natural choice through the established proof/ledger path and is
    # not a persistent schema field.
    next_question_node_id: str | None = None
    reply: str = ""
    handoff_requested: bool = False


class ConversationContext(StrictModel):
    persona_slug: str
    agent_slug: str
    graph_version: int = Field(ge=1)
    graph_checksum: str = Field(min_length=1)
    messages: list[dict[str, Any]]
    cart: dict[str, Any]
    rag_nodes: list[dict[str, Any]]
    rag_paths: list[list[str]]
    rag_chunks: list[dict[str, Any]] = Field(default_factory=list)
    context_cards: list[ContextCard] = Field(default_factory=list)
    system_prompt: str = ""
    # Values are not all strings: each anchor carries the graph's own `aliases`
    # list, which is what lets the model map natural wording onto a real anchor
    # id instead of the backend matching phrases itself.
    available_services: list[dict[str, Any]] = Field(default_factory=list)
    active_branch_node_id: str | None = None
    active_branch_node_ids: list[str] = Field(default_factory=list)
    # Branches (any offering -- service or product) already confirmed in this
    # ledger, per conversation_ledger_branches.state='completed'. Lets the
    # backend tell "this active branch already had its own confirmation
    # cycle" apart from "this one is new and still needs one" once a journey
    # has more than one active branch. See _decide's post_qualification_support
    # gate in graph_agent_runtime_v3.py.
    completed_branch_node_ids: list[str] = Field(default_factory=list)
    ledger_id: str | None = None
    active_path_checksum: str | None = None
    branch_node_ids: list[str] = Field(default_factory=list)
    graph_contract: dict[str, Any] = Field(default_factory=dict)
    publication_id: str | None = None
    runtime_version: str = "conversation_v2"
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)
    known_facts: list[dict[str, Any]] = Field(default_factory=list)
    time_since_last_client_message: str | None = None
    pending_reconfirmation: bool = False
    journey_id: str | None = None
    journey_sequence: int = Field(default=1, ge=1)
    journey_state: ConversationJourneyState = ConversationJourneyState.COLLECTING
    pending_field_key: str | None = None
    pending_question_node_id: str | None = None
    # Stable id of whatever the previous turn asked the customer to confirm.
    # A confirmation is only accepted when it names this ref, so "sim" with
    # nothing pending confirms nothing instead of confirming the last thing
    # that happens to be on the ledger.
    pending_confirmation_ref: str | None = None
    last_handoff: dict[str, Any] = Field(default_factory=dict)
    operational_mode: ConversationOperationalMode = ConversationOperationalMode.COLLECTION
    shared_memory: SharedLeadMemory = Field(default_factory=SharedLeadMemory)
    post_completion_state: dict[str, Any] = Field(default_factory=dict)


class ConversationDecision(StrictModel):
    classifier: str = "deterministic_v1"
    intent: str
    route: ConversationRoute
    confidence: float = Field(ge=0, le=1)
    cart_action: CartAction = CartAction.NONE
    product_slug: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    lead_stage: str
    handoff_reason: str | None = None
    evidence_node_ids: list[str] = Field(default_factory=list)


class AgentResponse(StrictModel):
    reply_text: str | None
    role: ConversationRoute
    evidence_node_ids: list[str] = Field(default_factory=list)
    cart_state: dict[str, Any]
    handoff_required: bool = False
    extracted_fields: dict[str, str] = Field(default_factory=dict)
    identified_service_slug: str | None = None
    proposal: ConversationProposal | None = None
    proof: dict[str, Any] = Field(default_factory=dict)
    repair_context_cards: list[dict[str, Any]] = Field(default_factory=list)
    # Billed usage reported by the reply-drafting model call (e.g. DeepSeek's
    # OpenAI-compatible {prompt_tokens, completion_tokens, total_tokens}).
    # Optional because not every route (deterministic fallbacks, HUMAN
    # handoff) makes a paid model call.
    token_usage: dict[str, Any] | None = None
