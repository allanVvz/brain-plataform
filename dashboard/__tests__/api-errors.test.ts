import { afterEach, describe, expect, it, vi } from "vitest";
import { API_OFFLINE_ERROR, ApiError, api } from "@/lib/api";

describe("API error taxonomy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("keeps a 403 as an authorization error instead of reporting an outage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "Acesso negado." }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    )));

    const error = await api.health().catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 403,
      path: "/health/score",
      kind: "forbidden",
      detail: "Acesso negado.",
    });
    expect(error.message).toContain("403 /health/score - Acesso negado.");
    expect(error.message).toContain("request_id");
    expect(error.requestId).not.toBe("");
    expect(error.message).not.toBe(API_OFFLINE_ERROR);
  });

  it.each([502, 503, 504])("classifies HTTP %s as backend unavailable", async (status) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status })));
    const error = await api.health().catch((caught) => caught);
    expect(error).toMatchObject({ status, kind: "unavailable" });
    expect(error.message).toContain(API_OFFLINE_ERROR);
    expect(error.message).toContain(`/health/score; HTTP ${status}`);
  });

  it("classifies a failed fetch as a network outage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("fetch failed");
    }));
    const error = await api.health().catch((caught) => caught);
    expect(error).toMatchObject({ status: 0, kind: "network" });
    expect(error.message).toContain(API_OFFLINE_ERROR);
    expect(error.message).toContain("/health/score; HTTP network");
  });

  it("retries bootstrap once on a transient gateway response and preserves request id", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ detail: "still unavailable" }),
        { status: 503, headers: { "x-request-id": "req-2" } },
      ));
    vi.stubGlobal("fetch", fetchMock);

    const error = await api.waBootstrap("generic").catch((caught) => caught);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(error).toMatchObject({ status: 503, requestId: "req-2" });
    expect(error.message).toContain("request_id req-2");
  });

  it("gives a preview-generating queue action a longer client timeout than a plain queue action", async () => {
    // Confirmed live on 2026-09-21: the default 15s budget cut off a real
    // operator-preview call (which asks runtime to run a full decide+proof
    // cycle) against a genuinely stuck lead. Plain queue writes (pause/
    // resume/send-preview) stay on the default -- they never call the model.
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, options: RequestInit) => new Promise((_, reject) => {
      options.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));

    const pauseSettled = vi.fn();
    const previewSettled = vi.fn();
    api.controlMessagingQueue("pause", { buffer_ids: ["b1"] }).catch(pauseSettled);
    api.controlMessagingQueue("operator-preview", { buffer_ids: ["b2"] }).catch(previewSettled);

    await vi.advanceTimersByTimeAsync(15_000);
    expect(pauseSettled).toHaveBeenCalledTimes(1);
    expect(previewSettled).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(30_000);
    expect(previewSettled).toHaveBeenCalledTimes(1);
  });
});
