import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import AudienceLeadsShortcut from "@/components/leads/AudienceLeadsShortcut";

afterEach(cleanup);

describe("AudienceLeadsShortcut", () => {
  it("renders a shortcut that opens Leads filtered by the audience slug", () => {
    render(<AudienceLeadsShortcut slug="tecnicos" />);
    const link = screen.getByTestId("audience-leads-shortcut") as HTMLAnchorElement;
    expect(link).toHaveTextContent(/Ver leads desta audience/i);
    expect(link.getAttribute("href")).toBe("/leads?audience=tecnicos");
  });

  it("renders nothing without a slug", () => {
    const { container } = render(<AudienceLeadsShortcut slug={null} />);
    expect(container.firstChild).toBeNull();
  });
});
