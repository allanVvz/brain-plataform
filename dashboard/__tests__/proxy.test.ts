import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { proxy } from "@/proxy";

describe("dashboard auth proxy", () => {
  it("preserves the complete protected destination in the login redirect", async () => {
    const response = await proxy(
      new NextRequest("http://localhost:3000/pipeline?view=crm&stage=novo"),
    );

    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") || "", "http://localhost:3000");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/pipeline?view=crm&stage=novo");
  });

  it("allows the login page without a session", async () => {
    const response = await proxy(new NextRequest("http://localhost:3000/login"));

    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });

  it("allows an authenticated request to continue", async () => {
    const request = new NextRequest("http://localhost:3000/pipeline", {
      headers: { cookie: "ai_brain_session=signed-token" },
    });

    const response = await proxy(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });
});
