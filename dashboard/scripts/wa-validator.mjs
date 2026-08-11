import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";
import { auditBrowserTurn, foldText } from "./wa-validator-driver.mjs";

function args() {
  const values = {};
  for (let index = 2; index < process.argv.length; index += 2) {
    values[process.argv[index]?.replace(/^--/, "")] = process.argv[index + 1];
  }
  return values;
}

async function exists(locator) {
  return (await locator.count()) > 0;
}

async function writeOutput(outputPath, output) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(output, null, 2), "utf8");
}

const options = args();
if (!options.script || !options.output || !options.profile) {
  throw new Error("--script, --output and --profile are required");
}

const script = JSON.parse(await fs.readFile(options.script, "utf8"));
const artifactDir = path.resolve(
  options.artifacts || path.join(path.dirname(options.output), "screenshots"),
);
await fs.mkdir(artifactDir, { recursive: true });
await fs.mkdir(path.resolve(options.profile), { recursive: true });

const output = {
  status: "starting",
  session_id: script.meta?.session_id,
  persona_slug: script.meta?.persona,
  agent_slug: script.meta?.agent_slug,
  graph_version: script.meta?.graph_version,
  graph_checksum: script.meta?.graph_checksum,
  conversation_mode: script.meta?.conversation_mode,
  classifier: script.meta?.classifier,
  pipeline_contract: script.meta?.pipeline_contract,
  conversation: [],
  screenshots: [],
  message_ids: [],
  assertions: [],
};
await writeOutput(options.output, output);

const context = await chromium.launchPersistentContext(path.resolve(options.profile), {
  headless: process.env.WA_VALIDATOR_HEADLESS !== "false",
  viewport: { width: 1440, height: 1000 },
  // WhatsApp Web rejects Playwright's default `HeadlessChrome` UA even when
  // the bundled Chromium is current. Keep the real engine version family and
  // omit only the automation-specific marker.
  userAgent:
    process.env.WA_VALIDATOR_USER_AGENT ||
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
});
const page = context.pages()[0] || (await context.newPage());
const authenticationWaitMs = Math.max(
  30_000,
  Math.min(Number(options["auth-wait-seconds"] || 30) * 1_000, 600_000),
);

try {
  await page.goto("https://web.whatsapp.com/", {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  const appReady = page.locator("#pane-side, [data-testid='chat-list']").first();
  try {
    await appReady.waitFor({ state: "visible", timeout: authenticationWaitMs });
  } catch {
    const screenshot = path.join(artifactDir, "authentication-required.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    const transportUnavailable = await page
      .getByText(/Computador desconectado|Computer disconnected|Computer offline/i)
      .isVisible()
      .catch(() => false);
    output.status = transportUnavailable
      ? "transport_unavailable"
      : "authentication_required";
    output.screenshots.push(screenshot);
    await writeOutput(options.output, output);
    process.exitCode = 2;
    throw new Error(
      transportUnavailable
        ? "__TRANSPORT_UNAVAILABLE__"
        : "__AUTHENTICATION_REQUIRED__",
    );
  }

  // WhatsApp periodically shows a release-notes modal after login. It blocks
  // the search field until dismissed.
  const continueButton = page.getByRole("button", { name: /^(Continuar|Continue)$/i }).first();
  if (await continueButton.isVisible().catch(() => false)) {
    await continueButton.click();
  } else {
    const closeButton = page.getByRole("button", { name: /^(Fechar|Close)$/i }).first();
    if (await closeButton.isVisible().catch(() => false)) {
      await closeButton.click();
    }
  }

  const target = String(script.target || "").trim();
  if (!target) throw new Error("script target is required");
  const targetDisplayName = target
    .split(/\s+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
  const inboundMessageSelector = [
    `[data-pre-plain-text*='${targetDisplayName}']`,
    "[data-id^='false_']",
    "[data-id*='_false_']",
    "[data-testid='msg-container'].message-in",
    ".message-in",
  ].join(", ");
  const targetPhoneDigits = String(script.target_phone || "").replace(/\D/g, "");
  if (targetPhoneDigits && !/^\d{10,15}$/.test(targetPhoneDigits)) {
    throw new Error("script target_phone must contain 10 to 15 digits");
  }
  const search = page
    .locator(
      "input[aria-label*='Search'], input[aria-label*='Pesquisar'], input[placeholder*='Search'], input[placeholder*='Pesquisar'], [data-testid='chat-list-search'] [contenteditable='true'], [aria-label*='Search'][contenteditable='true'], [aria-label*='Pesquisar'][contenteditable='true']",
    )
    .first();
  await search.click();
  await search.fill(target);
  await page.waitForTimeout(2_000);
  const escapedTarget = target.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matchingContacts = page
    .locator("[data-testid='cell-frame-container']")
    .filter({ hasText: new RegExp(`^\\s*${escapedTarget}\\b`, "i") });
  let matchingContactCount = await matchingContacts.count();
  let result = matchingContacts.first();
  if (matchingContactCount === 0) {
    const newChat = page
      .locator(
        "button[aria-label*='Nova conversa'], button[aria-label*='New chat'], [data-icon='new-chat-outline'], [data-icon='new-chat']",
      )
      .first();
    if (await newChat.isVisible().catch(() => false)) {
      await newChat.click({ noWaitAfter: true, timeout: 5_000 });
      const contactSearch = page
        .locator(
          "input[placeholder*='Pesquisar nome']:visible, input[placeholder*='Search name']:visible, input[aria-label*='Pesquisar nome']:visible, input[aria-label*='Search name']:visible, input[placeholder*='Pesquisar']:visible, input[placeholder*='Search']:visible",
        )
        .last();
      await contactSearch.waitFor({ state: "visible", timeout: 20_000 });
      await contactSearch.fill(target);
      await page.waitForTimeout(2_000);
      matchingContactCount = await matchingContacts.count();
      if (matchingContactCount === 0 && targetPhoneDigits) {
        await contactSearch.fill(`+${targetPhoneDigits}`);
        await page.waitForTimeout(2_000);
        const phoneResults = page.locator(
          "[data-testid='cell-frame-container']:visible",
        );
        matchingContactCount = await phoneResults.count();
        result = phoneResults.first();
        output.contact_resolution = {
          strategy: "e164_phone",
          target,
          phone_suffix: targetPhoneDigits.slice(-4),
        };
      } else if (matchingContactCount === 1) {
        output.contact_resolution = { strategy: "new_chat_name", target };
      }
    }
  } else {
    output.contact_resolution = { strategy: "existing_chat_name", target };
  }
  if (matchingContactCount !== 1) {
    throw new Error(
      `Expected exactly one contact for "${target}", found ${matchingContactCount}`,
    );
  }
  const activeChatHeader = page
    .locator("header")
    .filter({ hasText: new RegExp(`\\b${escapedTarget}\\b`, "i") })
    .first();
  if (!(await activeChatHeader.isVisible().catch(() => false))) {
    await result.waitFor({ state: "visible", timeout: 20_000 });
    await result.click();
  }

  const semanticDriver = script.driver?.mode === "semantic_graph_v1"
    ? script.driver
    : null;
  const stepQueue = semanticDriver
    ? [semanticDriver.opening]
    : [...(script.steps || [])];
  const knownFactKeys = new Set(semanticDriver?.initial_known_fields || []);
  const answeredFields = new Set();
  const recentBotReplies = [];
  let doubtSent = false;
  let switchSent = false;
  let semanticComplete = false;
  const maxTurns = semanticDriver
    ? Number(semanticDriver.max_turns || 1)
    : stepQueue.length;
  let index = 0;
  while (stepQueue.length > 0 && index < maxTurns) {
    const step = stepQueue.shift();
    const composer = page
      .locator(
        "[contenteditable='true'][role='textbox'][aria-placeholder*='Digite'], [contenteditable='true'][role='textbox'][aria-placeholder*='Type'], [contenteditable='true'][aria-label*='Digite'], [contenteditable='true'][aria-label*='Type'], footer [contenteditable='true'][role='textbox'], footer [contenteditable='true']",
      )
      .first();
    await composer.waitFor({ state: "visible", timeout: 20_000 });
    const inboundBefore = await page.locator(inboundMessageSelector).count();
    await composer.fill(String(step.text || ""));
    await composer.press("Enter");
    output.conversation.push({
      role: "validator",
      text: step.text,
      ts: new Date().toISOString(),
    });
    for (const key of Object.keys(step.intended_facts || {})) {
      knownFactKeys.add(key);
      if (step.kind === "field_answer") answeredFields.add(key);
    }
    const pendingOutbound = page
      .locator("[data-icon='msg-time'], [data-icon='msg-pending']")
      .last();
    if (await pendingOutbound.isVisible().catch(() => false)) {
      try {
        await pendingOutbound.waitFor({ state: "hidden", timeout: 20_000 });
      } catch {
        const screenshot = path.join(
          artifactDir,
          `${String(index + 1).padStart(2, "0")}-transport-pending.png`,
        );
        await page.screenshot({ path: screenshot, fullPage: true });
        output.screenshots.push(screenshot);
        output.status = "transport_unavailable";
        output.conversation.push({
          role: "transport",
          text: "(mensagem pendente no WhatsApp Web)",
          timeout: true,
          ts: new Date().toISOString(),
        });
        await writeOutput(options.output, output);
        process.exitCode = 2;
        throw new Error("__OUTBOUND_TRANSPORT_PENDING__");
      }
    }

    const waitMs = Math.max(1_000, Math.min(Number(step.wait || 15) * 1_000, 60_000));
    let timedOut = false;
    try {
      await page.waitForFunction(
        (count) =>
          document.querySelectorAll(
            "[data-id^='false_'], [data-id*='_false_'], [data-testid='msg-container'].message-in, .message-in",
          ).length > count,
        inboundBefore,
        { timeout: waitMs },
      );
    } catch {
      timedOut = true;
    }

    let botReplyText = "";
    const incoming = page
      .locator(inboundMessageSelector)
      .last();
    if (await exists(incoming)) {
      const text = (await incoming.innerText()).trim();
      botReplyText = text;
      const messageId = await incoming.getAttribute("data-id");
      if (
        !output.conversation.some(
          (turn) => turn.role === "bot" && turn.text === text,
        )
      ) {
        timedOut = false;
        output.conversation.push({
          role: "bot",
          text,
          message_id: messageId,
          ts: new Date().toISOString(),
        });
      }
      if (messageId) output.message_ids.push(messageId);
    }
    if (timedOut) {
      output.conversation.push({
        role: "bot",
        text: "(sem resposta dentro do prazo)",
        timeout: true,
        ts: new Date().toISOString(),
      });
    }
    const screenshot = path.join(
      artifactDir,
      `${String(index + 1).padStart(2, "0")}.png`,
    );
    await page.screenshot({ path: screenshot, fullPage: true });
    output.screenshots.push(screenshot);
    output.status = "running";
    await writeOutput(options.output, output);
    if (timedOut) {
      break;
    }
    if (semanticDriver) {
      const browserAudit = auditBrowserTurn({
        reply: botReplyText,
        questions: semanticDriver.questions || {},
        knownFactKeys,
        requiredFields: semanticDriver.required_fields || [],
        recentReplies: recentBotReplies,
        step,
      });
      for (const [name, passed] of Object.entries(browserAudit.criteria)) {
        output.assertions.push({
          name: `turn_${index + 1}:${name}`,
          passed,
          question_node_id: browserAudit.matchedQuestion?.questionId,
          field_key: browserAudit.matchedQuestion?.fieldKey,
        });
      }
      if (!browserAudit.passed) {
        throw new Error(
          `__SEMANTIC_FAILED__:${browserAudit.failures.join(",")}`,
        );
      }
      if (browserAudit.qualificationComplete) {
        semanticComplete = true;
        recentBotReplies.push(botReplyText);
        break;
      }
      const matchedQuestion = browserAudit.matchedQuestion;
      recentBotReplies.push(botReplyText);
      let nextStep = null;
      if (semanticDriver.doubt && !doubtSent) {
        doubtSent = true;
        nextStep = {
          ...semanticDriver.doubt,
          kind: "doubt",
          intended_facts: {},
        };
      } else if (
        semanticDriver.switch
        && !switchSent
        && answeredFields.size >= Number(
          semanticDriver.switch.after_answered_fields || 0,
        )
      ) {
        switchSent = true;
        nextStep = { ...semanticDriver.switch, kind: "branch_switch" };
      } else {
        const answer = semanticDriver.answers?.[matchedQuestion.fieldKey];
        if (answer?.text) {
          nextStep = {
            text: String(answer.text),
            kind: "field_answer",
            intended_facts: { [matchedQuestion.fieldKey]: answer.value },
          };
        }
      }
      if (!nextStep) {
        throw new Error(
          `__SEMANTIC_FAILED__:script_question_mismatch:${matchedQuestion.fieldKey}`,
        );
      }
      stepQueue.push(nextStep);
    }
    index += 1;
  }

  if (semanticDriver && !semanticComplete) {
    throw new Error("__SEMANTIC_FAILED__:driver_exhausted_before_completion");
  }
  output.status = "done";
  output.assertions.push({
    name: "graph_lineage_present",
    passed: Boolean(output.graph_version && output.graph_checksum),
  });
  output.assertions.push({
    name: "all_steps_sent",
    passed:
      semanticDriver
        ? semanticComplete
        : output.conversation.filter((turn) => turn.role === "validator").length ===
          (script.steps || []).length,
  });
  const botTurns = output.conversation.filter(
    (turn) => turn.role === "bot" && !turn.timeout,
  );
  output.assertions.push({
    name: "one_reply_per_step",
    passed:
      botTurns.length ===
      output.conversation.filter((turn) => turn.role === "validator").length,
    expected: output.conversation.filter((turn) => turn.role === "validator").length,
    actual: botTurns.length,
  });
  output.assertions.push({
    name: "no_reply_timeout",
    passed: !output.conversation.some((turn) => turn.timeout),
  });
  const normalizeText = (value) =>
    String(value || "")
      .toLowerCase()
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  const botText = normalizeText(botTurns.map((turn) => turn.text || "").join("\n"));
  const expectedDialogue = script.expected_dialogue || {};
  const brl = (value) =>
    Number(value).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });
  if (expectedDialogue.product_name) {
    output.assertions.push({
      name: "approved_product_mentioned",
      passed: botText.includes(normalizeText(expectedDialogue.product_name)),
    });
  }
  if (expectedDialogue.unit_price != null) {
    output.assertions.push({
      name: "approved_unit_price_mentioned",
      passed: botText.includes(normalizeText(brl(expectedDialogue.unit_price))),
      expected: brl(expectedDialogue.unit_price),
    });
  }
  if (expectedDialogue.final_total != null) {
    output.assertions.push({
      name: "deterministic_total_mentioned",
      passed: botText.includes(normalizeText(brl(expectedDialogue.final_total))),
      expected: brl(expectedDialogue.final_total),
    });
  }
  for (const term of expectedDialogue.forbidden_terms || []) {
    output.assertions.push({
      name: `forbidden_term_absent:${term}`,
      passed: !botText.includes(normalizeText(term)),
    });
  }
  output.status = output.assertions.every((item) => item.passed)
    ? "done"
    : "failed";
  output.technical_pass = output.assertions
    .filter((item) => ["one_reply_per_step", "no_reply_timeout"].includes(item.name))
    .every((item) => item.passed);
  output.quality_pass = semanticDriver
    ? output.assertions.every((item) => item.passed)
    : null;
  output.quality_scope = semanticDriver
    ? "browser_dynamic_dialogue"
    : "technical_only";
  await writeOutput(options.output, output);
} catch (error) {
  if (
    error instanceof Error &&
    (
      ["__AUTHENTICATION_REQUIRED__", "__TRANSPORT_UNAVAILABLE__"].includes(
        error.message,
      )
      || error.message === "__OUTBOUND_TRANSPORT_PENDING__"
    )
  ) {
    // The status and QR screenshot were already persisted above.
  } else {
  const message = error instanceof Error ? error.message : String(error);
  output.status = message.startsWith("__SEMANTIC_FAILED__") ? "failed" : "error";
  output.quality_pass = message.startsWith("__SEMANTIC_FAILED__") ? false : null;
  output.quality_scope = script.driver?.mode === "semantic_graph_v1"
    ? "browser_dynamic_dialogue"
    : "technical_only";
  output.error = message.replace(/^__SEMANTIC_FAILED__:/, "");
  try {
    const screenshot = path.join(artifactDir, "error.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    output.screenshots.push(screenshot);
  } catch {
    // The page may already be closed.
  }
  await writeOutput(options.output, output);
  process.exitCode = 1;
  }
} finally {
  await Promise.race([
    context.close().catch(() => undefined),
    new Promise((resolve) => setTimeout(resolve, 10_000)),
  ]);
  process.exit(process.exitCode ?? 0);
}
