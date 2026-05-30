import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import FaqGeneratorPanel from "@/components/graph/FaqGeneratorPanel";
import { api } from "@/lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const faqNode = { id: "gn:f1", data: { node_type: "faq", metadata: { faq_generation_count: 7 } } };
const productNode = { id: "gn:p1", data: { node_type: "product" } };

describe("FaqGeneratorPanel", () => {
  it("shows a disabled mock for non-FAQ node types", () => {
    render(<FaqGeneratorPanel node={productNode} personaSlug="allanvvz" />);
    expect(screen.getByText(/será ativada em breve/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Gerar$/ })).toBeNull();
  });

  it("on a FAQ node: generates, accepts, and appends to the same FAQ", async () => {
    const genSpy = vi.spyOn(api, "sofiaFaqGenerate").mockResolvedValue({
      faq_suggestions: [{ question: "Q1?", answer: "A1" }],
      faq_context: { parent_node_id: "p1" },
    } as any);
    const appendSpy = vi.spyOn(api, "sofiaFaqAppend").mockResolvedValue({ ok: true, created_node: false } as any);
    const onSaved = vi.fn();

    render(<FaqGeneratorPanel node={faqNode} personaSlug="allanvvz" onSaved={onSaved} />);

    // Default count comes from the node's saved faq_generation_count (7)
    expect((screen.getByDisplayValue("7") as HTMLInputElement).value).toBe("7");

    fireEvent.click(screen.getByRole("button", { name: /^Gerar$/ }));
    await waitFor(() => expect(genSpy).toHaveBeenCalled());
    expect(screen.getByDisplayValue("Q1?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Salvar no FAQ/i }));
    await waitFor(() => expect(appendSpy).toHaveBeenCalled());

    const payload = appendSpy.mock.calls[0][0] as any;
    expect(payload.faq_node_id).toBe("gn:f1");
    expect(payload.suggestions).toEqual([{ question: "Q1?", answer: "A1" }]);
    expect(onSaved).toHaveBeenCalled();
  });

  it("rejected suggestions are not persisted", async () => {
    vi.spyOn(api, "sofiaFaqGenerate").mockResolvedValue({
      faq_suggestions: [{ question: "Q1?", answer: "A1" }],
    } as any);
    const appendSpy = vi.spyOn(api, "sofiaFaqAppend").mockResolvedValue({ ok: true } as any);

    render(<FaqGeneratorPanel node={faqNode} personaSlug="allanvvz" />);
    fireEvent.click(screen.getByRole("button", { name: /^Gerar$/ }));
    await waitFor(() => expect(screen.getByDisplayValue("Q1?")).toBeInTheDocument());

    // Reject the only suggestion, then try to save
    fireEvent.click(screen.getByTitle("Rejeitar"));
    fireEvent.click(screen.getByRole("button", { name: /Salvar no FAQ/i }));

    await waitFor(() => expect(screen.getByText(/Aceite ao menos uma sugestão/i)).toBeInTheDocument());
    expect(appendSpy).not.toHaveBeenCalled();
  });
});
