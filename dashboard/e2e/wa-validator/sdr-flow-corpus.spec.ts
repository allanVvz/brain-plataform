import fs from "node:fs";
import path from "node:path";

import { expect, test } from "playwright/test";


const corpusPath = path.resolve(process.cwd(), "../tests/fixtures/sdr_flow_cases.json");
const corpus = JSON.parse(fs.readFileSync(corpusPath, "utf8")) as {
  version: number;
  cases: Array<Record<string, unknown> & { id: string; message: string }>;
};


test("WA Validator Playwright suite consumes the shared SDR regression corpus", async () => {
  expect(corpus.version).toBe(1);
  const byId = new Map(corpus.cases.map((item) => [item.id, item]));
  for (const id of [
    "greeting_after_handoff_oi",
    "greeting_after_handoff_oii",
    "greeting_with_service",
    "explicit_confirmation",
    "duplicate_terminal",
  ]) {
    expect(byId.has(id), id).toBeTruthy();
  }
  expect(byId.get("greeting_after_handoff_oii")?.must_not_ask_service).toBe(true);
  expect(byId.get("duplicate_terminal")?.max_outbounds).toBe(0);
});
