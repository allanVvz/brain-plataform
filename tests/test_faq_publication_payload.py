import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import supabase_client  # noqa: E402


def test_faq_publication_payload_prefers_explicit_question_answer_and_item_file_path():
    node = {
        "id": "node-1",
        "title": "Titulo do node",
        "slug": "faq-titulo",
        "summary": "Resumo",
        "persona_id": "persona-1",
        "tags": ["faq"],
        "metadata": {
            "question": "Qual e a durabilidade?",
            "answer": "A armacao foi feita para uso intenso.",
            "file_path": "AI-BRAIN/CLIENT/foo.md",
            "path_slugs": ["persona", "product", "faq"],
        },
    }
    item = {
        "persona_id": "persona-1",
        "title": "Pergunta do item",
        "content": "Resposta do item",
        "file_path": "FAQ/pergunta-real.md",
        "tags": ["faq", "durabilidade"],
    }
    edge = {"persona_id": "persona-1"}

    payload = supabase_client._faq_publication_payload(node, item, edge)

    assert payload["question"] == "Qual e a durabilidade?"
    assert payload["answer"] == "A armacao foi feita para uso intenso."
    assert payload["title"] == "Qual e a durabilidade?"
    assert payload["content"] == "A armacao foi feita para uso intenso."
    assert payload["file_path"] == "FAQ/pergunta-real.md"
    assert payload["path_slugs"] == ["persona", "product", "faq"]
    assert payload["persona_id"] == "persona-1"
    assert payload["tags"] == ["faq", "durabilidade"]


def test_faq_publication_payload_falls_back_to_item_title_and_content():
    node = {
        "id": "node-2",
        "title": "Fallback node title",
        "slug": "fallback-node-title",
        "summary": "Resumo do node",
        "metadata": {},
        "tags": ["faq"],
    }
    item = {
        "persona_id": "persona-2",
        "title": "Preco e beneficios",
        "content": "Resposta consolidada",
        "file_path": "FAQ/preco-beneficios.md",
        "tags": ["faq", "beneficios"],
    }

    payload = supabase_client._faq_publication_payload(node, item)

    assert payload["question"] == "Preco e beneficios"
    assert payload["answer"] == "Resposta consolidada"
    assert payload["file_path"] == "FAQ/preco-beneficios.md"
    assert payload["persona_id"] == "persona-2"
    assert payload["tags"] == ["faq", "beneficios"]
