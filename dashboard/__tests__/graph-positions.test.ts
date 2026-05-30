import { describe, expect, it } from "vitest";
import { compactRankMap } from "@/components/graph/knowledgeGraphLayout";
import {
  collectPositions,
  overlayPositions,
  positionsDiffer,
  type PositionedNode,
} from "@/lib/graphPositions";

describe("compactRankMap (vertical gap fix)", () => {
  it("maps sparse occupied ranks to consecutive levels", () => {
    // persona=0, brand=1, product=6, faq=9 -> 0,1,2,3 (no empty bands)
    const map = compactRankMap([0, 1, 6, 9]);
    expect(map.get(0)).toBe(0);
    expect(map.get(1)).toBe(1);
    expect(map.get(6)).toBe(2);
    expect(map.get(9)).toBe(3);
  });

  it("dedupes and sorts unordered ranks", () => {
    const map = compactRankMap([9, 6, 6, 0]);
    expect(map.get(0)).toBe(0);
    expect(map.get(6)).toBe(1);
    expect(map.get(9)).toBe(2);
  });
});

describe("graph node position persistence", () => {
  const node = (id: string, x: number, y: number): PositionedNode => ({ id, position: { x, y } });

  it("overlays saved positions, leaving new nodes on their computed spot", () => {
    const computed = [node("a", 0, 0), node("b", 100, 100)];
    const out = overlayPositions(computed, { a: { x: 50, y: 60 } });
    expect(out.find((n) => n.id === "a")?.position).toEqual({ x: 50, y: 60 });
    expect(out.find((n) => n.id === "b")?.position).toEqual({ x: 100, y: 100 });
  });

  it("ignores corrupt saved coordinates", () => {
    const computed = [node("a", 0, 0)];
    const out = overlayPositions(computed, { a: { x: NaN, y: 5 } } as any);
    expect(out[0].position).toEqual({ x: 0, y: 0 });
  });

  it("collectPositions rounds to whole px", () => {
    expect(collectPositions([node("a", 12.4, 7.8)])).toEqual({ a: { x: 12, y: 8 } });
  });

  it("positionsDiffer is false when layout matches saved (no churn)", () => {
    const nodes = [node("a", 10, 10), node("b", 20, 20)];
    const saved = collectPositions(nodes);
    expect(positionsDiffer(nodes, saved)).toBe(false);
  });

  it("positionsDiffer is true after a node moves or set changes", () => {
    const saved = { a: { x: 10, y: 10 } };
    expect(positionsDiffer([node("a", 11, 10)], saved)).toBe(true);
    expect(positionsDiffer([node("a", 10, 10), node("b", 0, 0)], saved)).toBe(true);
  });
});
