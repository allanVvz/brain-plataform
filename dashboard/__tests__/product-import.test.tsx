import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ImportMenu } from "@/components/products/ImportMenu";
import { ImportModal } from "@/components/products/ImportModal";
import { IntegrationConfigModal } from "@/components/tools/IntegrationConfigModal";
import { api } from "@/lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ImportMenu dropdown", () => {
  it("renders the 4 import options on open", () => {
    render(<ImportMenu onSelect={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Adicionar \/ Importar/i }));
    expect(screen.getByText(/Importar do Meta/i)).toBeInTheDocument();
    expect(screen.getByText(/Importar via CSV/i)).toBeInTheDocument();
    expect(screen.getByText(/Importar da Shopify/i)).toBeInTheDocument();
    expect(screen.getByText(/Scraper \(Mock\)/i)).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem")).toHaveLength(4);
  });

  it("calls onSelect with the chosen provider", () => {
    const onSelect = vi.fn();
    render(<ImportMenu onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Adicionar \/ Importar/i }));
    fireEvent.click(screen.getByText(/Importar via CSV/i));
    expect(onSelect).toHaveBeenCalledWith("csv");
  });
});

describe("ImportModal per provider", () => {
  it("opens on the CSV provider and shows a file input", () => {
    render(<ImportModal open initialProvider="csv" personaSlug="vz-lupas" onClose={() => {}} onImported={() => {}} />);
    expect(screen.getByRole("dialog", { name: /Importar produtos/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Arquivo CSV/i)).toBeInTheDocument();
  });

  it("Shopify provider previews, audits collections, then imports selected items with download flag", async () => {
    const previewSpy = vi.spyOn(api, "previewImport").mockResolvedValue({
      collections: [
        { key: "radar", label: "Radar", count: 2, products: [
          { external_id: "r1", title: "Radar 1", thumbnail: "https://cdn/r1.jpg", item: { external_id: "r1" } },
          { external_id: "r2", title: "Radar 2", thumbnail: null, item: { external_id: "r2" } },
        ] },
      ],
      total: 2,
    } as any);
    const importSpy = vi.spyOn(api, "importProducts").mockResolvedValue({ created: 2, updated: 0, skipped: 0, total: 2, images_downloaded: 1 } as any);
    const onImported = vi.fn();
    render(<ImportModal open initialProvider="shopify" personaSlug="vz-lupas" onClose={() => {}} onImported={onImported} />);

    // step 1: URL -> Pre-visualizar
    fireEvent.change(screen.getByPlaceholderText(/collections\/all/i), { target: { value: "vzlupas.com" } });
    fireEvent.click(screen.getByRole("button", { name: /Pre-visualizar/i }));
    await waitFor(() => expect(previewSpy).toHaveBeenCalledWith("shopify", expect.objectContaining({ config: { url: "vzlupas.com" } })));

    // step 2: audit shows the collection + products, then import selected (2)
    await waitFor(() => expect(screen.getByText("Radar")).toBeInTheDocument());
    expect(screen.getByText("Radar 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Importar selecionados \(2\)/i }));
    await waitFor(() => expect(importSpy).toHaveBeenCalled());
    expect(importSpy.mock.calls[0][0]).toBe("shopify");
    expect(importSpy.mock.calls[0][1].items).toHaveLength(2);
    expect(importSpy.mock.calls[0][1].download_images).toBe(true);
    await waitFor(() => expect(onImported).toHaveBeenCalled());
    expect(screen.getByText(/imagens baixadas: 1/i)).toBeInTheDocument();
  });

  it("audit lets you disable a collection to exclude its products", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      collections: [
        { key: "radar", label: "Radar", count: 1, products: [{ external_id: "r1", title: "Radar 1", item: { external_id: "r1" } }] },
        { key: "juliet", label: "Juliet", count: 1, products: [{ external_id: "j1", title: "Juliet 1", item: { external_id: "j1" } }] },
      ],
      total: 2,
    } as any);
    const importSpy = vi.spyOn(api, "importProducts").mockResolvedValue({ created: 1, updated: 0, skipped: 0, total: 1 } as any);
    render(<ImportModal open initialProvider="shopify" personaSlug="vz-lupas" onClose={() => {}} onImported={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/collections\/all/i), { target: { value: "vzlupas.com" } });
    fireEvent.click(screen.getByRole("button", { name: /Pre-visualizar/i }));
    await waitFor(() => expect(screen.getByText("Juliet")).toBeInTheDocument());
    // uncheck the Juliet collection
    fireEvent.click(screen.getByLabelText(/Coleção Juliet/i));
    await waitFor(() => expect(screen.getByRole("button", { name: /Importar selecionados \(1\)/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Importar selecionados \(1\)/i }));
    await waitFor(() => expect(importSpy).toHaveBeenCalled());
    expect(importSpy.mock.calls[0][1].items).toEqual([{ external_id: "r1" }]);
  });

  it("Meta provider imports through the saved integration (no token field)", async () => {
    const spy = vi.spyOn(api, "importProducts").mockResolvedValue({ created: 1, updated: 0, skipped: 0, total: 1 } as any);
    render(<ImportModal open initialProvider="meta" personaSlug="vz-lupas" onClose={() => {}} onImported={() => {}} />);
    expect(screen.queryByLabelText(/Access Token/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Importar$/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("meta", expect.objectContaining({ persona_slug: "vz-lupas" })));
  });
});

describe("IntegrationConfigModal (Meta)", () => {
  const metaService = { key: "meta", label: "Meta", desc: "Catalogo WhatsApp Business" };

  it("shows only Business ID, Catalog ID and a masked Access Token", () => {
    render(<IntegrationConfigModal service={metaService} data={{ status: "unknown" }} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByLabelText(/Business ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Catalog ID/i)).toBeInTheDocument();
    const token = screen.getByLabelText(/Access Token/i) as HTMLInputElement;
    expect(token.type).toBe("password");
    // no "nome da conexao" field
    expect(screen.queryByLabelText(/nome da conex/i)).toBeNull();
  });

  it("Testar conexao calls validateUserIntegration and reflects healthy status", async () => {
    const spy = vi.spyOn(api, "validateUserIntegration").mockResolvedValue({ status: "healthy" } as any);
    render(<IntegrationConfigModal service={metaService} data={{ status: "unknown" }} onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText(/Catalog ID/i), { target: { value: "CAT-9" } });
    fireEvent.change(screen.getByLabelText(/Access Token/i), { target: { value: "tok" } });
    fireEvent.click(screen.getByRole("button", { name: /Testar conexao/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("meta", expect.objectContaining({ catalog_id: "CAT-9", access_token: "tok" })));
    await waitFor(() => expect(screen.getByText(/status: healthy/i)).toBeInTheDocument());
  });

  it("Salvar persists via updateUserIntegration enabled=true", async () => {
    const spy = vi.spyOn(api, "updateUserIntegration").mockResolvedValue({ status: "healthy" } as any);
    const onSaved = vi.fn();
    render(<IntegrationConfigModal service={metaService} data={{ status: "unknown" }} onClose={() => {}} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/Catalog ID/i), { target: { value: "CAT-9" } });
    fireEvent.change(screen.getByLabelText(/Access Token/i), { target: { value: "tok" } });
    fireEvent.click(screen.getByRole("button", { name: /Salvar/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("meta", expect.objectContaining({ enabled: true, catalog_id: "CAT-9" })));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
