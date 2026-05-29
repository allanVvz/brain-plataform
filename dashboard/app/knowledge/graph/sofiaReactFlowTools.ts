export type SofiaReactFlowToolName =
  | "apply_patch_visual"
  | "mark_pending"
  | "undo_pending"
  | "confirm_pending"
  | "select_node"
  | "focus_node"
  | "update_layout"
  | "highlight_edges";

export interface SofiaReactFlowToolContext {
  message?: string;
  personaSlug?: string;
  nodeId?: string;
  value?: string;
}

export interface SofiaReactFlowToolDefinition {
  name: SofiaReactFlowToolName;
  command: (context: SofiaReactFlowToolContext) => string;
}

function requireValue(value: string | undefined, fallback: string): string {
  return String(value || "").trim() || fallback;
}

export const SOFIA_REACT_FLOW_TOOLS: Record<SofiaReactFlowToolName, SofiaReactFlowToolDefinition> = {
  apply_patch_visual: {
    name: "apply_patch_visual",
    command: (context) => requireValue(context.message, "apply_patch_visual"),
  },
  mark_pending: {
    name: "mark_pending",
    command: () => "mark_pending",
  },
  undo_pending: {
    name: "undo_pending",
    command: () => "undo_pending",
  },
  confirm_pending: {
    name: "confirm_pending",
    command: () => "confirm_pending",
  },
  select_node: {
    name: "select_node",
    command: (context) => `select_node ${requireValue(context.value || context.nodeId, "")}`.trim(),
  },
  focus_node: {
    name: "focus_node",
    command: (context) => `focus_node ${requireValue(context.value || context.nodeId, "")}`.trim(),
  },
  update_layout: {
    name: "update_layout",
    command: (context) => `update_layout ${requireValue(context.value, "")}`.trim(),
  },
  highlight_edges: {
    name: "highlight_edges",
    command: (context) => `highlight_edges ${requireValue(context.value || context.nodeId, "")}`.trim(),
  },
};

const TOOL_PREFIXES: Array<{ prefix: string; tool: SofiaReactFlowToolName }> = [
  { prefix: "/select ", tool: "select_node" },
  { prefix: "/focus ", tool: "focus_node" },
  { prefix: "/layout ", tool: "update_layout" },
  { prefix: "/highlight ", tool: "highlight_edges" },
  { prefix: "/apply ", tool: "apply_patch_visual" },
  { prefix: "/patch ", tool: "apply_patch_visual" },
];

export function resolveSofiaToolFromInput(text: string): { tool: SofiaReactFlowToolName; value?: string } | null {
  const normalized = String(text || "").trim();
  const lower = normalized.toLowerCase();
  for (const item of TOOL_PREFIXES) {
    if (!lower.startsWith(item.prefix)) continue;
    return {
      tool: item.tool,
      value: normalized.slice(item.prefix.length).trim(),
    };
  }
  return null;
}
