import { describe, expect, it } from "vitest";
import {
  acceptedPayload,
  clampFaqCount,
  defaultFaqCount,
  toEditableSuggestions,
  type FaqSuggestion,
} from "@/lib/faq";

describe("clampFaqCount", () => {
  it("defaults and clamps", () => {
    expect(clampFaqCount(undefined)).toBe(5);
    expect(clampFaqCount(0)).toBe(5);
    expect(clampFaqCount(999)).toBe(20);
    expect(clampFaqCount("7")).toBe(7);
  });
});

describe("defaultFaqCount", () => {
  it("uses the node's saved faq_generation_count for 'gerar novamente'", () => {
    expect(defaultFaqCount({ data: { metadata: { faq_generation_count: 8 } } })).toBe(8);
    expect(defaultFaqCount({ metadata: { faq_generation_count: 3 } })).toBe(3);
    expect(defaultFaqCount({ data: {} })).toBe(5);
  });
});

describe("toEditableSuggestions / acceptedPayload", () => {
  it("seeds suggestions accepted by default", () => {
    const out = toEditableSuggestions([{ question: "Q1", answer: "A1" }, { question: "Q2" }]);
    expect(out).toHaveLength(2);
    expect(out.every((s) => s.accepted)).toBe(true);
    expect(out[1].answer).toBe("");
  });

  it("persists only accepted, non-empty suggestions", () => {
    const list: FaqSuggestion[] = [
      { question: "Q1", answer: "A1", accepted: true },
      { question: "Q2", answer: "A2", accepted: false },
      { question: "   ", answer: "A3", accepted: true },
    ];
    expect(acceptedPayload(list)).toEqual([{ question: "Q1", answer: "A1" }]);
  });
});
