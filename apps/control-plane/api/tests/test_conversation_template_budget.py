import json
from pathlib import Path


TEMPLATE = Path(__file__).parents[4] / "apps" / "conversation-runtime" / "n8n" / "persona-conversation-template.json"


def test_conversation_template_uses_published_rag_context_without_persona_rules():
    workflow = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    code = next(node for node in workflow["nodes"] if node["id"] == "model_request")["parameters"]["jsCode"]

    assert "const approvedChunks" in code
    assert "retained_chunk_count" in code
    assert "provider_managed" in code
    assert "aurora" not in code.lower()
    assert "tock-fatal" not in code.lower()
