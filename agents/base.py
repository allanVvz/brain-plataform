import httpx
from schemas.context import Context


class BaseAgent:
    name: str = "base"
    model: str = "unknown"

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    async def run(self, ctx: Context) -> dict:
        payload = {
            "lead_id": ctx.lead.id,
            "nome": ctx.lead.nome,
            "stage": ctx.lead.stage,
            "canal": ctx.lead.canal,
            "mensagem": ctx.mensagem,
            "interesse_produto": ctx.lead.interesse_produto,
            "cidade": ctx.lead.cidade,
            "cep": ctx.lead.cep,
            "classification": ctx.classification,
            "kb_chunks": ctx.kb_chunks,
            "historico": ctx.historico[-5:],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.endpoint, json=payload)
            response.raise_for_status()
            result = response.json()
            result["agent"] = self.name
            result["model"] = self.model
            return result
