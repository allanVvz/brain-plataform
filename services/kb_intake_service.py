"""
KB Intake Service — conversational classifier for knowledge ingestion.
Writes to vault → git commit → sync Supabase.
"""
import os
import base64
import json
import re
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from services import supabase_client
from services.vault_sync import run_sync, VAULT_PATH
from services.model_router import ModelRouter, ModelRouterError

AVAILABLE_MODELS = {
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5 — Rápido",
    "claude-sonnet-4-6":         "Claude Sonnet 4.6 — Balanceado",
    "claude-opus-4-7":           "Claude Opus 4.7 — Mais capaz",
}

_VAULT_CLIENT_FOLDERS = {
    "tock-fatal":        "TOCK_FATAL",
    "vz-lupas":          "VZ_LUPAS",
    "baita-conveniencia":"BAITA_CONVENIENCIA",
    "global":            "00_GLOBAL",
}

_CONTENT_TYPE_FOLDERS = {
    "brand":         "01_BRAND",
    "briefing":      "02_BRIEFING",
    "product":       "03_PRODUCTS",
    "campaign":      "04_CAMPAIGNS",
    "copy":          "05_COPY",
    "faq":           "06_FAQ",
    "tone":          "07_TONE",
    "audience":      "08_AUDIENCE",
    "competitor":    "09_COMPETITORS",
    "rule":          "10_RULES",
    "prompt":        "11_PROMPTS",
    "maker_material":"12_MAKER",
    "asset":         "assets",
    "other":         "00_OTHER",
}

_CONTENT_ALIASES = {
    "faq": "faq", "pergunta": "faq", "perguntas": "faq", "kb": "faq",
    "produto": "product", "product": "product",
    "copy": "copy",
    "campanha": "campaign", "campaign": "campaign",
    "briefing": "briefing",
    "tom": "tone", "tone": "tone",
    "moodboard": "maker_material", "maker": "maker_material",
    "regra": "rule", "rule": "rule",
}

_PERSONA_ALIASES = {
    "tock fatal": "tock-fatal",
    "tock-fatal": "tock-fatal",
    "tock_fatal": "tock-fatal",
    "vz lupas": "vz-lupas",
    "vz-lupas": "vz-lupas",
    "baita conveniencia": "baita-conveniencia",
    "baita conveniência": "baita-conveniencia",
    "baita-conveniencia": "baita-conveniencia",
}

_ASSET_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".mp4", ".pdf", ".ai", ".psd"}

_sessions: dict[str, dict] = {}
_SESSION_DIR = Path(os.environ.get("KB_INTAKE_SESSION_DIR", ".runtime/kb-intake-sessions"))

_SYSTEM_PROMPT = """Você é o KB Classifier, um agente especializado em classificar materiais para a base de conhecimento da plataforma AI Brain.

Sua função: conduzir uma conversa objetiva para coletar as informações necessárias de classificação. Seja direto e eficiente — máximo 2 perguntas por mensagem.

=== CLIENTES DISPONÍVEIS ===
- tock-fatal → Tock Fatal (marca de moda urbana)
- vz-lupas → VZ Lupas (óculos e saúde visual)
- baita-conveniencia → Baita Conveniência (bar e conveniência)
- global → Global (aplicável a todos os clientes)

=== TIPOS DE CONTEÚDO TEXTUAL ===
brand, briefing, product, campaign, copy, faq, tone, audience, competitor, rule, prompt, maker_material, other

=== PARA ASSETS VISUAIS ===
Tipo de asset: background, logo, product, model, banner, story, post, video, icon, other
Função do asset: maker_material, brand_reference, campaign_hero, copy_support, product_showcase, other

=== FLUXO DE CLASSIFICAÇÃO ===
1. Identifique o cliente (obrigatório)
2. Identifique se é asset visual ou conteúdo textual
3. Se asset: pergunte tipo e função
4. Se texto: identifique o tipo de conteúdo
5. Confirme o título (sugira um se não houver)
6. Quando completo, apresente um resumo e pergunte se pode salvar

Você consegue extrair múltiplas informações de uma única mensagem. Por exemplo, se o usuário diz "background do Tock Fatal", você já sabe cliente=tock-fatal, content_type=asset, asset_type=background.

Responda SEMPRE em português. Seja conciso.

Ao final de cada resposta, inclua obrigatoriamente o bloco de estado (mesmo que incompleto):
<classification>
{
  "complete": false,
  "persona_slug": null,
  "content_type": null,
  "asset_type": null,
  "asset_function": null,
  "title": null
}
</classification>

Quando TODAS as informações estiverem coletadas E confirmadas pelo usuário, marque "complete": true.
"""


def _extract_cls(text: str) -> Optional[dict]:
    match = re.search(r"<classification>(.*?)</classification>", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except Exception:
        return None


def _strip_cls(text: str) -> str:
    return re.sub(r"\s*<classification>.*?</classification>", "", text, flags=re.DOTALL).strip()


def _session_path(session_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    return _SESSION_DIR / f"{safe}.json"


def _serialize_session(session: dict) -> dict:
    data = json.loads(json.dumps(session, default=str))
    raw = session.get("classification", {}).get("file_bytes")
    if isinstance(raw, (bytes, bytearray)):
        data.setdefault("classification", {})["file_bytes_b64"] = base64.b64encode(raw).decode("ascii")
        data["classification"]["file_bytes"] = None
    return data


def _save_session(session: dict) -> None:
    try:
        _SESSION_DIR.mkdir(parents=True, exist_ok=True)
        _session_path(session["id"]).write_text(
            json.dumps(_serialize_session(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_session(session_id: str) -> Optional[dict]:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
        b64 = session.get("classification", {}).pop("file_bytes_b64", None)
        if b64:
            session["classification"]["file_bytes"] = base64.b64decode(b64)
        _sessions[session_id] = session
        return session
    except Exception:
        return None


def _get_session(session_id: str) -> Optional[dict]:
    return _sessions.get(session_id) or _load_session(session_id)


def create_session(model: str = "claude-sonnet-4-6") -> dict:
    sid = str(uuid.uuid4())
    session = {
        "id": sid,
        "model": model,
        "stage": "chatting",
        "messages": [],
        "classification": {
            "persona_slug": None,
            "content_type": None,
            "asset_type": None,
            "asset_function": None,
            "title": None,
            "file_ext": None,
            "file_bytes": None,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sessions[sid] = session
    _save_session(session)
    return session


def get_session(session_id: str) -> Optional[dict]:
    return _get_session(session_id)


def chat(session_id: str, user_message: str, file_info: Optional[dict] = None) -> dict:
    session = _get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    cls = session["classification"]

    if file_info:
        ext = file_info.get("ext", "")
        cls["file_ext"] = ext
        if file_info.get("bytes"):
            cls["file_bytes"] = file_info["bytes"]
        file_desc = f"[Arquivo: {file_info['filename']} — {len(file_info.get('bytes', b''))} bytes]"
        user_content = f"{file_desc}\n{user_message}".strip() if user_message else file_desc
    else:
        user_content = user_message

    session["messages"].append({"role": "user", "content": user_content})

    state_ctx = f"""
Estado atual:
- Cliente: {cls['persona_slug'] or '—'}
- Tipo de conteúdo: {cls['content_type'] or '—'}
- Tipo de asset: {cls['asset_type'] or '—'}
- Função do asset: {cls['asset_function'] or '—'}
- Título: {cls['title'] or '—'}
- Arquivo binário recebido: {'Sim (' + cls['file_ext'] + ')' if cls.get('file_bytes') else 'Não'}
"""

    try:
        router = ModelRouter()
        raw = router.messages_create(
            model=session["model"],
            messages=session["messages"],
            system=_SYSTEM_PROMPT + "\n\n" + state_ctx,
            max_tokens=1024,
        )
    except ModelRouterError as exc:
        session["messages"].pop()  # roll back the user message on failure
        _save_session(session)
        return {"error": f"LLM indisponível: {exc}"}
    except Exception as exc:
        session["messages"].pop()
        _save_session(session)
        return {"error": f"Erro inesperado no LLM: {exc}"}

    cls_data = _extract_cls(raw)
    visible = _strip_cls(raw)

    if cls_data:
        for key in ("persona_slug", "content_type", "asset_type", "asset_function", "title"):
            if cls_data.get(key):
                cls[key] = cls_data[key]
        if cls_data.get("complete"):
            session["stage"] = "ready_to_save"

    session["messages"].append({"role": "assistant", "content": raw})
    _apply_save_inference(session)
    _save_session(session)

    return {
        "message": visible,
        "stage": session["stage"],
        "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
    }


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\s\-]", "_", name).strip().replace(" ", "_")


def _fold(text: str) -> str:
    import unicodedata
    normalized = unicodedata.normalize("NFKD", text or "")
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _infer_from_transcript(session: dict) -> dict:
    transcript = "\n".join(str(m.get("content") or "") for m in session.get("messages", []))
    visible = _strip_cls(transcript)
    folded = _fold(visible)
    inferred: dict = {}

    def label_key(label: str) -> str | None:
        normalized = _fold(label).strip().replace("?", "")
        if normalized == "cliente":
            return "persona_slug"
        if normalized in {"tipo", "tipo de conteudo", "tipo de contedo"}:
            return "content_type"
        if normalized in {"titulo", "ttulo"}:
            return "title"
        if normalized in {"descricao", "descrio"}:
            return "description"
        if normalized == "link":
            return "link"
        return None
    for line in visible.splitlines():
        clean = line.strip().lstrip("-").strip()
        if ":" not in clean:
            continue
        label, value = clean.split(":", 1)
        key = label_key(label)
        if key and value.strip():
            inferred[key] = value.strip().strip("-").strip()

    if inferred.get("persona_slug"):
        key = _fold(inferred["persona_slug"]).strip()
        inferred["persona_slug"] = _PERSONA_ALIASES.get(key, key.replace(" ", "-"))
    else:
        for alias, slug in _PERSONA_ALIASES.items():
            if alias in folded:
                inferred["persona_slug"] = slug
                break

    if inferred.get("content_type"):
        key = _fold(inferred["content_type"]).strip()
        inferred["content_type"] = _CONTENT_ALIASES.get(key, key)
    else:
        for alias, ctype in _CONTENT_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", folded):
                inferred["content_type"] = ctype
                break

    return inferred


def _apply_save_inference(session: dict) -> None:
    cls = session["classification"]
    inferred = _infer_from_transcript(session)
    for key in ("persona_slug", "content_type", "title"):
        if inferred.get(key) and (not cls.get(key) or cls.get(key) == "other"):
            cls[key] = inferred[key]
    if inferred.get("description"):
        cls["description"] = inferred["description"]
    if inferred.get("link"):
        cls["link"] = inferred["link"]


def _build_content(session: dict, content_text: str) -> str:
    if content_text and content_text.strip():
        return content_text.strip()
    cls = session["classification"]
    inferred = _infer_from_transcript(session)
    description = cls.get("description") or inferred.get("description") or ""
    link = cls.get("link") or inferred.get("link") or ""

    if cls.get("content_type") == "faq":
        lines = [f"Pergunta: {cls.get('title') or 'FAQ'}"]
        lines.append(f"Resposta: {description}" if description else "Resposta: ")
        if link:
            lines.extend(["", f"Link: {link}"])
        return "\n".join(lines)

    lines: list[str] = []
    if description:
        lines.extend(["## Descrição", "", description, ""])
    if link:
        lines.extend(["## Link", "", link, ""])
    return "\n".join(lines).strip()


def _write_file(session: dict, content_text: str) -> Path:
    cls = session["classification"]
    vault_root = Path(VAULT_PATH)
    client_folder = _VAULT_CLIENT_FOLDERS.get(cls["persona_slug"] or "global", "00_GLOBAL")
    type_folder = _CONTENT_TYPE_FOLDERS.get(cls["content_type"] or "other", "00_OTHER")
    safe_title = _safe_filename(cls["title"] or "untitled")

    ext = cls.get("file_ext") or ""
    is_binary_asset = ext.lower() in _ASSET_EXTS and cls.get("file_bytes")

    if is_binary_asset:
        target_dir = vault_root / "AI-BRAIN" / "05_ENTITIES" / "CLIENTS" / client_folder / "assets"
        filename = f"{safe_title}{ext}"
    else:
        target_dir = vault_root / "AI-BRAIN" / "05_ENTITIES" / "CLIENTS" / client_folder / type_folder
        filename = f"{safe_title}.md"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if is_binary_asset:
        target_path.write_bytes(cls["file_bytes"])
    else:
        now = datetime.now(timezone.utc).isoformat()
        lines = ["---", f"title: {cls['title']}", f"client: {cls['persona_slug']}",
                 f"type: {cls['content_type']}"]
        if cls.get("link"):
            lines.append(f"link: {cls['link']}")
        if cls.get("asset_type"):
            lines.append(f"asset_type: {cls['asset_type']}")
        if cls.get("asset_function"):
            lines.append(f"asset_function: {cls['asset_function']}")
        lines += [f"created_at: {now}", "---", "", content_text or ""]
        target_path.write_text("\n".join(lines), encoding="utf-8")

    return target_path


def _git_ops(vault_path: str, rel_path: str, title: str, client: str) -> dict:
    def run(args: list, **kw) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=vault_path, capture_output=True, text=True, timeout=60, **kw)

    add = run(["git", "add", rel_path])
    commit = run(["git", "commit", "-m", f"kb: add {title} [{client}]"])
    push = run(["git", "push"])

    return {
        "add_ok": add.returncode == 0,
        "commit_ok": commit.returncode == 0,
        "push_ok": push.returncode == 0,
        "commit_out": commit.stdout.strip()[:200],
        "push_err": push.stderr.strip()[:200],
    }


def save(session_id: str, content_text: str = "") -> dict:
    session = _get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    _apply_save_inference(session)
    cls = session["classification"]
    missing = [k for k in ("persona_slug", "content_type", "title") if not cls.get(k)]
    if missing:
        return {
            "error": "Classification incomplete — missing " + ", ".join(missing),
            "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
        }

    content_text = _build_content(session, content_text)

    # ── 1. Write to vault (mandatory) ──────────────────────────────────
    try:
        file_path = _write_file(session, content_text)
    except Exception as e:
        return {"error": f"Write failed: {e}"}

    rel_path = str(file_path.relative_to(Path(VAULT_PATH)))

    # ── 2. Git (best-effort) ───────────────────────────────────────────
    # If git is not on PATH or the vault isn't a repo, the call raises
    # FileNotFoundError/CalledProcessError. We surface that as a non-fatal
    # status instead of letting FastAPI 500 the whole request.
    try:
        git_result = _git_ops(VAULT_PATH, rel_path, cls["title"], cls["persona_slug"])
    except Exception as exc:
        git_result = {
            "add_ok": False, "commit_ok": False, "push_ok": False,
            "error": f"git unavailable: {exc}".strip()[:200],
        }

    # ── 3. Vault sync into knowledge_items (best-effort) ───────────────
    try:
        sync_result = run_sync(VAULT_PATH, persona_filter=cls["persona_slug"])
    except Exception as exc:
        sync_result = {"error": f"sync failed: {exc}".strip()[:200], "new": 0, "updated": 0}

    # ── 4. Audit event (best-effort) ──────────────────────────────────
    try:
        supabase_client.insert_event({
            "event_type": "kb_intake",
            "payload": {
                "title": cls["title"],
                "persona_slug": cls["persona_slug"],
                "content_type": cls["content_type"],
                "file_path": rel_path,
                "git": git_result,
                "sync_new": sync_result.get("new", 0),
                "sync_updated": sync_result.get("updated", 0),
            },
        })
    except Exception:
        pass  # insert_event is fire-and-forget anyway

    session["stage"] = "done"
    _save_session(session)

    return {
        "ok": True,
        "file_path": rel_path,
        "git": git_result,
        "sync": {
            "new": sync_result.get("new", 0),
            "updated": sync_result.get("updated", 0),
            "error": sync_result.get("error"),
        },
    }
