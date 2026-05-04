#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

from services import kb_intake_service as svc


class _FakeRouter:
    def messages_create(self, **kwargs):
        return (
            "Resposta curta.\n"
            "<classification>{\"complete\": false, \"persona_slug\": \"vz-lupas\", \"content_type\": \"briefing\", "
            "\"asset_type\": null, \"asset_function\": null, \"title\": \"Briefing VZ Lupas\"}</classification>"
        )


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"ok {msg}")


def main() -> int:
    old = svc.ModelRouter
    try:
        svc.ModelRouter = _FakeRouter  # type: ignore[assignment]
        s = svc.create_session(
            model="gpt-4o-mini",
            initial_context=(
                "persona_slug: tock-fatal\n"
                "objetivo: Criar conhecimento de marketing para Tock Fatal.\n"
                "fonte principal: https://tockfatal.com/\n"
                "## Blocos de conhecimento solicitados\n"
                "- briefing: x\n- audience: y\n- product: z\n- copy: c\n- faq: f\n"
            ),
            agent_key="sofia",
        )
        sid = s["id"]

        r1 = svc.chat(sid, "quero mudar o site e a persona. quero mudar para Vz lupas no site Vzlupas.com")
        _assert(r1.get("ok") is True, "chat ok after persona/site change")
        st = r1.get("state") or {}
        _assert(st.get("persona") == "vz-lupas", "persona changed to vz-lupas")
        _assert((st.get("source") or {}).get("url") == "https://vzlupas.com", "source url changed")

        old_blocks = list(st.get("knowledge_blocks") or [])
        r2 = svc.chat(sid, "os mesmos")
        _assert(r2.get("ok") is True, "chat ok on 'os mesmos'")
        st2 = r2.get("state") or {}
        _assert((st2.get("knowledge_blocks") or []) == old_blocks, "knowledge blocks preserved")

        svc.chat(sid, "traga 2 modelos Juliet e Radar Ev. Traga 10 produtos de cada. preço ângulo faq para cada um")
        r4 = svc.chat(sid, "Faça 2 públicos. Street e coloque a Juliet. e Esportes e coloque as Radar Ev")
        st4 = r4.get("state") or {}
        models = st4.get("requested_outputs", {}).get("models", [])
        juliet = next((m for m in models if (m.get("name") or "").lower() == "juliet"), {})
        radar = next((m for m in models if "radar" in (m.get("name") or "").lower()), {})
        _assert(juliet.get("audience") == "Street", "Juliet mapped to Street")
        _assert(radar.get("audience") == "Esportes", "Radar Ev mapped to Esportes")
        _assert(juliet.get("products_requested") == 10, "products requested set to 10")

        # Simulate crawler failure path with invalid URL in mission source.
        st4["source"] = {"type": "website", "url": "https://invalid.invalid"}
        svc._save_session(svc.get_session(sid))  # type: ignore[arg-type]
        r5 = svc.chat(sid, "colete o site")
        _assert("state" in r5, "error/success payload includes state")
        if r5.get("crawler"):
            _assert(r5["crawler"].get("confidence_label") in {"baixa", "media", "alta"}, "crawler returns confidence label")

        print(f"PASS integration_kb_intake_stateful at {datetime.now(timezone.utc).isoformat()}")
        return 0
    finally:
        svc.ModelRouter = old  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(main())
