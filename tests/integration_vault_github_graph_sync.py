# -*- coding: utf-8 -*-
"""
Offline validation for GitHub-backed vault sync.

This test does not use a local vault repository and does not call GitHub. It
monkeypatches the GitHub API helpers, sync storage functions and graph mirror.

Run:
  python tests/integration_vault_github_graph_sync.py
"""
from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeStore:
    def __init__(self) -> None:
        self.personas = {
            "prime-higienizacao": {"id": "persona-prime", "slug": "prime-higienizacao"},
        }
        self.source: dict | None = None
        self.run = {"id": "sync-run-1"}
        self.items: dict[str, dict] = {}
        self.logs: list[dict] = []
        self.graph_calls: list[dict] = []

    def get_persona(self, slug: str) -> dict | None:
        return deepcopy(self.personas.get(slug))

    def get_knowledge_source_by_path(self, path: str) -> dict | None:
        return deepcopy(self.source) if self.source and self.source.get("path") == path else None

    def insert_knowledge_source(self, data: dict) -> dict:
        self.source = {**deepcopy(data), "id": "source-github-vault"}
        return deepcopy(self.source)

    def insert_sync_run(self, data: dict) -> dict:
        self.run = {**deepcopy(data), "id": "sync-run-1"}
        return deepcopy(self.run)

    def update_sync_run(self, run_id: str, data: dict) -> None:
        self.run.update(deepcopy(data))

    def update_knowledge_source(self, source_id: str, data: dict) -> None:
        assert self.source and self.source["id"] == source_id
        self.source.update(deepcopy(data))

    def insert_sync_log(self, data: dict) -> None:
        self.logs.append(deepcopy(data))

    def get_knowledge_item_by_path(self, path: str) -> dict | None:
        return deepcopy(self.items.get(path))

    def insert_knowledge_item(self, data: dict) -> dict:
        row = {**deepcopy(data), "id": f"item-{len(self.items) + 1}"}
        self.items[row["file_path"]] = row
        return deepcopy(row)

    def update_knowledge_item(self, item_id: str, data: dict) -> None:
        for row in self.items.values():
            if row["id"] == item_id:
                row.update(deepcopy(data))
                return
        raise AssertionError(f"missing item {item_id}")


def main() -> int:
    from services import event_emitter, knowledge_graph, supabase_client, vault_sync

    store = FakeStore()
    env_keys = [
        "VAULT_SOURCE_MODE",
        "GITHUB_VAULT_REPO",
        "GITHUB_VAULT_BRANCH",
        "GITHUB_VAULT_ROOT",
        "GITHUB_TOKEN",
    ]
    old_env = {key: os.environ.get(key) for key in env_keys}
    originals = {
        "get_persona": supabase_client.get_persona,
        "get_knowledge_source_by_path": supabase_client.get_knowledge_source_by_path,
        "insert_knowledge_source": supabase_client.insert_knowledge_source,
        "insert_sync_run": supabase_client.insert_sync_run,
        "update_sync_run": supabase_client.update_sync_run,
        "update_knowledge_source": supabase_client.update_knowledge_source,
        "insert_sync_log": supabase_client.insert_sync_log,
        "get_knowledge_item_by_path": supabase_client.get_knowledge_item_by_path,
        "insert_knowledge_item": supabase_client.insert_knowledge_item,
        "update_knowledge_item": supabase_client.update_knowledge_item,
        "bootstrap_from_item": knowledge_graph.bootstrap_from_item,
        "_github_get_json": vault_sync._github_get_json,
        "_github_get_text": vault_sync._github_get_text,
        "emit": event_emitter.emit,
    }

    def fake_github_json(url: str, headers: dict) -> dict:
        assert "git/trees/main?recursive=1" in url, url
        assert headers["Authorization"] == "Bearer test-token"
        return {
            "tree": [
                {"type": "blob", "path": "vault/PRIME_HIGIENIZACAO/produtos/cadeiras.md"},
                {"type": "blob", "path": "vault/PRIME_HIGIENIZACAO/faq/preco-cadeiras.md"},
                {"type": "blob", "path": "vault/.obsidian/workspace.json"},
            ]
        }

    def fake_github_text(url: str, headers: dict) -> str:
        if "produtos/cadeiras.md?ref=main" in url:
            return (
                "---\n"
                "cliente: prime-higienizacao\n"
                "type: product\n"
                "title: Higienizacao de Cadeiras Prime\n"
                "slug: higienizacao-cadeiras-prime\n"
                "campaign: Operacao Limpeza\n"
                "---\n"
                "Servico de higienizacao de cadeiras em Novo Hamburgo.\n"
            )
        return (
            "---\n"
            "cliente: prime-higienizacao\n"
            "type: faq\n"
            "title: Quanto custa Higienizacao de Cadeiras Prime?\n"
            "product: Higienizacao de Cadeiras Prime\n"
            "---\n"
            "Pergunta: Quanto custa Higienizacao de Cadeiras Prime?\n"
            "Resposta: Custa R$ 100,00 por cadeira.\n"
        )

    def fake_bootstrap(item, frontmatter=None, body="", persona_id=None, source_table="knowledge_items"):
        store.graph_calls.append({
            "item": deepcopy(item),
            "frontmatter": deepcopy(frontmatter or {}),
            "body": body,
            "persona_id": persona_id,
            "source_table": source_table,
        })
        return {"id": f"graph-{len(store.graph_calls)}", "level": 40, "importance": 0.85}

    try:
        os.environ["VAULT_SOURCE_MODE"] = "github"
        os.environ["GITHUB_VAULT_REPO"] = "acme/ai-brain-vault"
        os.environ["GITHUB_VAULT_BRANCH"] = "main"
        os.environ["GITHUB_VAULT_ROOT"] = "vault"
        os.environ["GITHUB_TOKEN"] = "test-token"

        supabase_client.get_persona = store.get_persona
        supabase_client.get_knowledge_source_by_path = store.get_knowledge_source_by_path
        supabase_client.insert_knowledge_source = store.insert_knowledge_source
        supabase_client.insert_sync_run = store.insert_sync_run
        supabase_client.update_sync_run = store.update_sync_run
        supabase_client.update_knowledge_source = store.update_knowledge_source
        supabase_client.insert_sync_log = store.insert_sync_log
        supabase_client.get_knowledge_item_by_path = store.get_knowledge_item_by_path
        supabase_client.insert_knowledge_item = store.insert_knowledge_item
        supabase_client.update_knowledge_item = store.update_knowledge_item
        knowledge_graph.bootstrap_from_item = fake_bootstrap
        vault_sync._github_get_json = fake_github_json
        vault_sync._github_get_text = fake_github_text
        event_emitter.emit = lambda *args, **kwargs: None

        preview = vault_sync.scan_vault()
        assert preview["source_mode"] == "github", preview
        assert preview["total"] == 2, preview
        assert preview["by_client"]["prime-higienizacao"] == 2, preview

        result = vault_sync.run_sync(persona_filter="prime-higienizacao")
        assert result["found"] == 2 and result["new"] == 2, result
        assert store.source and store.source["path"] == "github://acme/ai-brain-vault@main/vault", store.source
        assert len(store.graph_calls) == 2, store.graph_calls
        assert all(c["source_table"] == "knowledge_items" for c in store.graph_calls), store.graph_calls
        assert {row["content_type"] for row in store.items.values()} == {"product", "faq"}, store.items
        assert all(row["metadata"]["source_mode"] == "github" for row in store.items.values()), store.items
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for name, fn in originals.items():
            if name in {"bootstrap_from_item"}:
                setattr(knowledge_graph, name, fn)
            elif name.startswith("_github"):
                setattr(vault_sync, name, fn)
            elif name == "emit":
                setattr(event_emitter, name, fn)
            else:
                setattr(supabase_client, name, fn)

    print("PASS GitHub vault sync: API source -> pending items -> graph mirror, no local repo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
