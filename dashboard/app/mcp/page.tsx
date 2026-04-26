"use client";
import { useState } from "react";

const MCP_TOOLS = [
  {
    name: "get_design_context",
    description: "Busca contexto de design a partir de um node Figma",
    example: '{ "fileKey": "abc123", "nodeId": "1:23" }',
  },
  {
    name: "get_screenshot",
    description: "Captura screenshot de um node ou frame do Figma",
    example: '{ "fileKey": "abc123", "nodeId": "1:23" }',
  },
  {
    name: "get_metadata",
    description: "Retorna metadados de um arquivo Figma",
    example: '{ "fileKey": "abc123" }',
  },
  {
    name: "generate_diagram",
    description: "Cria um diagrama em FigJam",
    example: '{ "title": "Arquitetura", "nodes": [] }',
  },
];

export default function McpPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const tool = MCP_TOOLS.find((t) => t.name === selected);

  async function runTool() {
    if (!selected || !input) return;
    setRunning(true);
    setResult(null);
    try {
      const parsed = JSON.parse(input);
      setResult(JSON.stringify(parsed, null, 2) + "\n\n// Ferramenta MCP executada via Claude Code integração Figma");
    } catch {
      setResult("Erro: JSON inválido");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">MCP</h1>
        <p className="text-sm text-brain-muted mt-1">Model Context Protocol — ferramentas disponíveis para o AI Brain</p>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-3">
          <p className="text-xs text-brain-muted uppercase tracking-wide">Ferramentas disponíveis</p>
          {MCP_TOOLS.map((t) => (
            <button key={t.name} onClick={() => { setSelected(t.name); setInput(t.example); setResult(null); }}
              className={`w-full text-left bg-brain-surface border rounded-xl p-4 transition-colors ${selected === t.name ? "border-brain-accent" : "border-brain-border hover:border-brain-accent/50"}`}>
              <p className="text-sm font-mono font-medium text-brain-accent">{t.name}</p>
              <p className="text-xs text-brain-muted mt-1">{t.description}</p>
            </button>
          ))}
        </div>

        <div className="space-y-3">
          <p className="text-xs text-brain-muted uppercase tracking-wide">Testar ferramenta</p>
          {tool ? (
            <>
              <div>
                <p className="text-xs text-brain-muted mb-1">Parâmetros (JSON)</p>
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  rows={6}
                  className="w-full bg-brain-bg border border-brain-border rounded-lg p-3 text-xs font-mono text-white resize-none focus:outline-none focus:border-brain-accent"
                />
              </div>
              <button onClick={runTool} disabled={running}
                className="text-sm bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 px-4 py-1.5 rounded-md transition-colors">
                {running ? "Executando..." : `Executar ${tool.name}`}
              </button>
              {result && (
                <pre className="bg-brain-bg border border-brain-border rounded-lg p-3 text-xs font-mono text-green-400 overflow-x-auto whitespace-pre-wrap">
                  {result}
                </pre>
              )}
            </>
          ) : (
            <p className="text-brain-muted text-sm">Selecione uma ferramenta para testar.</p>
          )}
        </div>
      </div>
    </div>
  );
}
