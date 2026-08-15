import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageBubble, ConversationMediaRail } from "@/app/messages/MessagesLayout";

function message(overrides: any = {}) {
  return {
    id: 1,
    lead_ref: 42,
    message_id: "m-1",
    sender_type: "lead",
    canal: "whatsapp",
    texto: "",
    status: "delivered",
    direction: "inbound",
    metadata: {},
    created_at: "2026-08-14T12:00:00Z",
    Lead_Stage: null,
    nome: "Ana",
    ...overrides,
  };
}

describe("message media", () => {
  it("renders an audio player for a received voice note", () => {
    const { container } = render(
      <MessageBubble
        msg={message({
          texto: "[audio do cliente]: quanto custa a juliet preta?",
          metadata: {
            asset_id: "asset-1",
            media: { kind: "audio", voice_note: true, duration_seconds: 7 },
          },
        })}
        lead={null}
      />,
    );

    const audio = container.querySelector("audio");
    expect(audio).toBeInTheDocument();
    expect(audio?.getAttribute("src")).toContain("/assets/asset-1/media");
    expect(screen.getByText(/Mensagem de voz/)).toBeInTheDocument();
    // The transcription is the user's turn and must stay visible.
    expect(screen.getByText(/quanto custa a juliet preta/)).toBeInTheDocument();
  });

  it("shows both the caption and the image", () => {
    // Regression: media used to render only when `texto` was empty, so a
    // photo sent with a caption silently lost the photo.
    const { container } = render(
      <MessageBubble
        msg={message({
          texto: "quanto custa essa?",
          metadata: { asset_id: "asset-2", media: { kind: "image", mime: "image/jpeg" } },
        })}
        lead={null}
      />,
    );

    expect(screen.getByText("quanto custa essa?")).toBeInTheDocument();
    const img = container.querySelector("img");
    expect(img).toBeInTheDocument();
    expect(img?.getAttribute("src")).toContain("/assets/asset-2/media");
  });

  it("marks an attachment as still downloading before its bytes land", () => {
    render(
      <MessageBubble
        msg={message({
          texto: "[o cliente enviou um audio]",
          metadata: { media: { kind: "audio", voice_note: true } },
        })}
        lead={null}
      />,
    );

    expect(screen.getByText(/baixando áudio/)).toBeInTheDocument();
  });

  it("still renders a plain text message untouched", () => {
    const { container } = render(
      <MessageBubble msg={message({ texto: "bom dia" })} lead={null} />,
    );

    expect(screen.getByText("bom dia")).toBeInTheDocument();
    expect(container.querySelector("audio")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows a stable failure state instead of an endless media spinner", () => {
    render(
      <MessageBubble
        msg={message({
          texto: "[o cliente enviou uma imagem]",
          metadata: {
            asset_id: "asset-failed",
            media_asset_status: "failed",
            media: { kind: "image", mime: "image/jpeg" },
          },
        })}
        lead={null}
      />,
    );

    expect(screen.getByText(/indisponivel para visualizacao/)).toBeInTheDocument();
    expect(screen.queryByText(/baixando arquivo/)).not.toBeInTheDocument();
  });

  it("renders a document chip with its filename", () => {
    render(
      <MessageBubble
        msg={message({
          metadata: {
            asset_id: "asset-3",
            media: { kind: "document", filename: "pedido.pdf", mime: "application/pdf" },
          },
        })}
        lead={null}
      />,
    );

    expect(screen.getByText("pedido.pdf")).toBeInTheDocument();
  });
});

describe("conversation media rail", () => {
  it("lists the files exchanged in the thread", () => {
    render(
      <ConversationMediaRail
        messages={[
          message({ id: 1, texto: "bom dia" }),
          message({
            id: 2,
            metadata: { asset_id: "a-1", media: { kind: "image" } },
          }),
          message({
            id: 3,
            metadata: { asset_id: "a-2", media: { kind: "audio", voice_note: true } },
          }),
        ] as any}
      />,
    );

    // Two attachments among three messages.
    expect(screen.getByText(/Mídia · Arquivos · Links · 2/)).toBeInTheDocument();
  });

  it("says so honestly when nothing has been exchanged", () => {
    render(<ConversationMediaRail messages={[message({ texto: "bom dia" })] as any} />);

    expect(screen.getByText("Nenhum arquivo trocado nesta conversa ainda.")).toBeInTheDocument();
  });
});
