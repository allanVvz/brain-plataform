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
    ROOT / "apps" / "control-plane" / "api" / "services" / "graph_bundle_publisher.py"
).read_text(encoding="utf-8")
RELEASE_WORKFLOW = (
    ROOT / ".github" / "workflows" / "release-main.yml"
).read_text(encoding="utf-8")


def test_graph_bundle_publisher_is_scoped_to_one_persona_and_not_bindings():
    assert 'persona_slug = normalized["persona"]["slug"]' in GRAPH_BUNDLE_PUBLISHER
    assert 'raise GraphBundlePublishError("persona_scope_mismatch")' in GRAPH_BUNDLE_PUBLISHER
    assert '"persona_id": persona_id' in GRAPH_BUNDLE_PUBLISHER
    assert "workflow_bindings" not in GRAPH_BUNDLE_PUBLISHER


def test_content_only_changes_do_not_build_or_deploy_images():
    policy = (ROOT / "ops/release/release-services.json").read_text(encoding="utf-8")
    assert '"ci_only"' in policy
    assert "needs.classify.outputs.build_images == 'true'" in RELEASE_WORKFLOW


def test_documents_keep_pause_and_publisher_scope_explicit():
    for document in (AGENTS, ROADMAP, RELEASE_GATES):
        assert "persona" in document.lower()

    assert "Persona nova sem binding/workflow/transporte ja e inerte" in AGENTS
    assert "GraphBundle" in ROADMAP
    assert "GraphBundle" in RELEASE_GATES
    assert "Personas não\nenvolvidas continuam operando" in ROADMAP
    assert "it does not\n  publish a GraphBundle" in RELEASE_GATES
