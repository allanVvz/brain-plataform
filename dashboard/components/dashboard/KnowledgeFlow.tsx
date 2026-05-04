"use client";

import { useMemo, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Edge,
  MarkerType,
  Node,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { BrainCircuit, ImageIcon, LineChart } from "lucide-react";

interface KnowledgeFlowProps {
  totalKnowledgeItems: number;
  validatedKnowledgeItems: number;
  crmInferencesCount: number;
  makerInferencesCount: number;
}

const nodeDescriptions = {
  brain: "Conteudos validados que serao usados como fonte de treinamento e inferencia.",
  crm: "Usa conhecimentos validados para gerar inferencias comerciais, segmentacoes e recomendacoes de relacionamento.",
  maker: "Usa imagens, briefing e assets para gerar inferencias visuais e criativas.",
};

export function KnowledgeFlow({
  totalKnowledgeItems,
  validatedKnowledgeItems,
  crmInferencesCount,
  makerInferencesCount,
}: KnowledgeFlowProps) {
  const [selectedNode, setSelectedNode] = useState<"brain" | "crm" | "maker">("brain");
  const nodes = useMemo<Node[]>(
    () => [
      {
        id: "brain",
        position: { x: 300, y: 45 },
        sourcePosition: Position.Bottom,
        data: {
          label: (
            <NodeCard
              title="Brain"
              value={`${validatedKnowledgeItems}/${totalKnowledgeItems}`}
              description={nodeDescriptions.brain}
              icon={<BrainCircuit size={18} />}
              selected={selectedNode === "brain"}
            />
          ),
        },
        type: "default",
        style: { width: 260, background: "transparent", border: "none", padding: 0 },
      },
      {
        id: "crm",
        position: { x: 110, y: 300 },
        targetPosition: Position.Top,
        data: {
          label: (
            <NodeCard
              title="CRM"
              value={String(crmInferencesCount)}
              description={nodeDescriptions.crm}
              icon={<LineChart size={18} />}
              selected={selectedNode === "crm"}
            />
          ),
        },
        style: { width: 260, background: "transparent", border: "none", padding: 0 },
      },
      {
        id: "maker",
        position: { x: 490, y: 300 },
        targetPosition: Position.Top,
        data: {
          label: (
            <NodeCard
              title="Maker"
              value={String(makerInferencesCount)}
              description={nodeDescriptions.maker}
              icon={<ImageIcon size={18} />}
              selected={selectedNode === "maker"}
            />
          ),
        },
        style: { width: 260, background: "transparent", border: "none", padding: 0 },
      },
    ],
    [crmInferencesCount, makerInferencesCount, selectedNode, totalKnowledgeItems, validatedKnowledgeItems],
  );

  const edges = useMemo<Edge[]>(
    () => [
      {
        id: "brain-crm",
        source: "brain",
        target: "crm",
        label: "usa",
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#7c6fff" },
        style: { stroke: "#7c6fff", strokeWidth: 1.6 },
        labelStyle: { fill: "#8892a4", fontSize: 10 },
      },
      {
        id: "brain-maker",
        source: "brain",
        target: "maker",
        label: "usa",
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#7c6fff" },
        style: { stroke: "#7c6fff", strokeWidth: 1.6 },
        labelStyle: { fill: "#8892a4", fontSize: 10 },
      },
    ],
    [],
  );

  const selectedDescription = nodeDescriptions[selectedNode];

  return (
    <section className="animate-fade-in rounded-xl border border-white/06 bg-white/[0.025] p-5 lg:p-6">
      <div className="mb-5 flex flex-col gap-1">
        <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
          Knowledge Flow
        </p>
        <h2 className="text-lg font-semibold text-obs-text">Brain alimentando CRM e Maker</h2>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="h-[520px] overflow-hidden rounded-xl border border-white/06 bg-obs-deep">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            minZoom={0.55}
            maxZoom={1.3}
            onNodeClick={(_, node) => setSelectedNode(node.id as "brain" | "crm" | "maker")}
            nodesDraggable
            nodesConnectable={false}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgba(255,255,255,0.12)" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        <aside className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
          <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">Selecionado</p>
          <h3 className="mt-2 text-lg font-semibold capitalize text-obs-text">{selectedNode}</h3>
          <p className="mt-3 text-sm leading-relaxed text-obs-subtle">{selectedDescription}</p>
          <div className="mt-5 space-y-2 text-sm">
            <Metric label="Knowledge items" value={totalKnowledgeItems} />
            <Metric label="Validados" value={validatedKnowledgeItems} />
            <Metric label="CRM inferencias" value={crmInferencesCount} />
            <Metric label="Maker inferencias" value={makerInferencesCount} />
          </div>
        </aside>
      </div>
    </section>
  );
}

function NodeCard({
  title,
  value,
  description,
  icon,
  selected,
}: {
  title: string;
  value: string;
  description: string;
  icon: React.ReactNode;
  selected: boolean;
}) {
  return (
    <div className={`rounded-xl border p-4 text-left shadow-obs-node ${selected ? "border-obs-violet/60 bg-obs-violet/15" : "border-white/08 bg-obs-surface"}`}>
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/08 bg-white/[0.04] text-obs-violet">
          {icon}
        </span>
        <div>
          <p className="text-sm font-semibold text-obs-text">{title}</p>
          <p className="text-xl font-semibold text-white">{value}</p>
        </div>
      </div>
      <p className="mt-3 line-clamp-3 text-xs leading-relaxed text-obs-subtle">{description}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-white/06 bg-obs-base px-3 py-2">
      <span className="text-obs-subtle">{label}</span>
      <span className="font-semibold text-obs-text">{value}</span>
    </div>
  );
}
