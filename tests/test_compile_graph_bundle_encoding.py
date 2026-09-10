"""O plano compilado precisa sair em UTF-8, senao vira baseline corrompida.

Os cards sao em portugues, entao o JSON do plano tem acento. No Windows o
stdout assume cp1252 e cada `ç` sai como byte que nao e UTF-8 valido. Como o
plano de uma versao vira o arquivo `--against` da proxima, o consumidor lia um
documento diferente do compilado e o checksum nunca podia bater: o erro
aparecia como `baseline_checksum_invalid`, culpando o bundle por um defeito de
codificacao. Foi o que bloqueou a publicacao v31 do site da Tock Fatal.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps/control-plane/api/scripts/compile_graph_bundle.py"


def test_plan_stdout_is_pinned_to_utf8() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'reconfigure(encoding="utf-8")' in source, (
        "compile_graph_bundle.py precisa fixar UTF-8 no stdout; sem isso o "
        "plano sai em cp1252 no Windows e a baseline da proxima versao chega "
        "corrompida ao compilador."
    )
    # A fixacao tem de valer para qualquer chamador, nao depender de o
    # operador lembrar de exportar PYTHONIOENCODING antes de rodar.
    assert source.index("reconfigure") < source.index("build_publication_plan("), (
        "o stdout precisa ser fixado antes de qualquer emissao do plano."
    )
