from pathlib import Path


ROOT = Path(__file__).parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ROADMAP = (ROOT / "docs" / "roadmaps" / "AGENT_ROADMAP.md").read_text(
    encoding="utf-8"
)
RELEASE_GATES = (
    ROOT / "docs" / "runbooks" / "PRODUCTION_RELEASE_GATES.md"
).read_text(encoding="utf-8")
GRAPH_BUNDLE_PUBLISHER = (
    ROOT / "api" / "services" / "graph_bundle_publisher.py"
).read_text(encoding="utf-8")
CONTENT_WORKFLOW = (
    ROOT / ".github" / "workflows" / "publish-content.yml"
).read_text(encoding="utf-8")


def test_graph_bundle_publisher_is_scoped_to_one_persona_and_not_bindings():
    assert 'persona_slug = normalized["persona"]["slug"]' in GRAPH_BUNDLE_PUBLISHER
    assert 'raise GraphBundlePublishError("persona_scope_mismatch")' in GRAPH_BUNDLE_PUBLISHER
    assert "persona_id=persona_id" in GRAPH_BUNDLE_PUBLISHER
    assert "workflow_bindings" not in GRAPH_BUNDLE_PUBLISHER


def test_legacy_content_workflow_is_not_the_graph_bundle_publisher():
    assert "publish_persona_documents.py" in CONTENT_WORKFLOW
    assert "publish_graph_bundle.py" not in CONTENT_WORKFLOW
    assert "approved-draft-checksum" not in CONTENT_WORKFLOW
    assert "approved-runtime-checksum" not in CONTENT_WORKFLOW


def test_documents_keep_pause_and_publisher_scope_explicit():
    for document in (AGENTS, ROADMAP, RELEASE_GATES):
        assert "persona" in document.lower()

    assert "Persona nova sem binding/workflow/transporte ja e inerte" in AGENTS
    assert "GraphBundle" in ROADMAP
    assert "GraphBundle" in RELEASE_GATES
    assert "Personas não envolvidas continuam operando" in ROADMAP
    assert "it does not\n  publish a GraphBundle" in RELEASE_GATES
