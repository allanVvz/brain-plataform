import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";

describe("explicit client portal API context", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the requested slug for every portal CRM call", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      calls.push(String(input));
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }));

    await api.portalLeads("aurora");
    await api.portalConversations("aurora");
    await api.portalConversationMessages("aurora", 42);
    await api.portalKnowledgeChatContext("aurora", 42, "lavagem");
    await api.portalPipeline("aurora");

    expect(calls).toEqual([
      "/api-brain/portal/leads?persona_slug=aurora&limit=500",
      "/api-brain/portal/conversations?persona_slug=aurora",
      "/api-brain/portal/conversations/42/messages?persona_slug=aurora",
      "/api-brain/portal/knowledge/chat-context?persona_slug=aurora&lead_ref=42&limit=12&q=lavagem",
      "/api-brain/portal/pipeline?persona_slug=aurora",
    ]);
  });

  it("never redirects an admin API method through portal state", async () => {
    localStorage.setItem("ai-brain-account-type", "client");
    localStorage.setItem("ai-brain-persona-slug", "aurora");
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      calls.push(String(input));
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }));

    await api.leads();
    await api.conversations();
    await api.pipelineStatus();

    expect(calls).toEqual([
      "/api-brain/leads?limit=100&offset=0",
      "/api-brain/messages/conversations?hours=168",
      "/api-brain/pipeline/status",
    ]);
  });
});
