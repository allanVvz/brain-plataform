# Configuração das perguntas do SDR

O GraphBundle publicado é a configuração de perguntas do SDR. Use
`question_modes` no bloco de qualificação da Persona:

```json
{
  "conversation_policy": {
    "qualification": {
      "question_modes": {
        "nome_cliente": "optional",
        "modelo_veiculo": "required",
        "cor_veiculo": "disabled"
      }
    }
  }
}
```

Em personas de agendamento, a mesma propriedade fica em
`appointment_policy.question_modes`. Valores aceitos: `required`, `optional` e
`disabled`. Campo sem entrada explícita conserva o `required` já declarado.

Os campos continuam no contrato compilado para que fatos já coletados e novas
respostas continuem reconhecíveis. `required` participa da completude;
`optional` pode ser perguntado sem bloquear conclusão; `disabled` não deve ser
perguntado proativamente. Uma resposta espontânea continua podendo preencher o
campo. As declarações e perguntas do grafo são autoria e contexto; não obrigam o
modelo a copiar o texto nem a seguir uma ordem fixa.

Para revisar sem publicar, execute:

```sh
PYTHONPATH=apps/control-plane/api python3 apps/control-plane/api/scripts/compile_graph_bundle.py caminho/bundle.json
```

Para publicar, use o fluxo GraphBundle existente: aprove o `draft_checksum` e o
`runtime_checksum` do plano e execute `apps/control-plane/api/scripts/publish_graph_bundle.py`
com esses checksums. A ativação continua sendo CAS e preserva a publicação
anterior se houver falha. Não há tabela nem migration nova.
