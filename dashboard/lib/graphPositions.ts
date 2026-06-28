/**
 * Per-persona node position persistence for the Graph tab.
 *
 * Positions are saved to localStorage keyed by persona + view mode. On refresh
 * the saved JSON is overlaid on the computed layout so manual arrangements
 * survive, and we only write back when a position actually changed (so an
 * incidental re-render never churns storage or nudges the screen).
 */
export type XY = { x: number; y: number };

export interface PositionedNode {
  id: string;
  position: XY;
}

export function readPositions(key: string): Record<string, XY> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as Record<string, XY>) : {};
  } catch {
    return {};
  }
}

export function writePositions(key: string, positions: Record<string, XY>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(positions));
  } catch {
    // Storage full / unavailable — non-fatal, layout still works in-memory.
  }
}

/** Overlay saved positions onto computed layout nodes (new nodes keep their computed spot). */
export function overlayPositions<T extends PositionedNode>(nodes: T[], saved: Record<string, XY>): T[] {
  if (!saved || !Object.keys(saved).length) return nodes;
  return nodes.map((node) => {
    const pos = saved[node.id];
    if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
      return { ...node, position: { x: pos.x, y: pos.y } };
    }
    return node;
  });
}

/** Snapshot current node positions (rounded to whole px to keep the JSON stable). */
export function collectPositions(nodes: PositionedNode[]): Record<string, XY> {
  const map: Record<string, XY> = {};
  for (const node of nodes) {
    map[node.id] = { x: Math.round(node.position.x), y: Math.round(node.position.y) };
  }
  return map;
}

/** True when the live layout differs from what is stored — the "só altera se houver diferença" guard. */
export function positionsDiffer(nodes: PositionedNode[], saved: Record<string, XY>): boolean {
  const current = collectPositions(nodes);
  const currentKeys = Object.keys(current);
  if (currentKeys.length !== Object.keys(saved || {}).length) return true;
  for (const id of currentKeys) {
    const prev = saved[id];
    if (!prev || prev.x !== current[id].x || prev.y !== current[id].y) return true;
  }
  return false;
}
