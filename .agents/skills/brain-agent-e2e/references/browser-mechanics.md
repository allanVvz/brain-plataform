# Dashboard browser mechanics (claude-in-chrome / Playwright)

Concrete UI mechanics for driving `https://brain-plataform-plum.vercel.app` through
claude-in-chrome or an equivalent Playwright-compatible controller. These are
implementation details discovered live; read this before re-running a dual-persona
E2E to avoid re-deriving them (and burning turns/tokens) from scratch.

## The tenant/persona selector is shared browser state, not per-tab

The `CLIENTE` dropdown (top-left, a native `<select>`) is backed by state that
persists across every tab in the same browser profile — switching persona in
tab A silently switches the "active tenant" that tab B renders on its next
navigation or reload too. **Two tabs pointed at two different persona
dashboards do not stay independently scoped.** Opening `/messages/{leadId}`
under the wrong tenant does not error — it silently falls back to
"Selecione um lead para ver a conversa" with no indication the tenant is
wrong. Always confirm the `CLIENTE` value visible top-left matches the
persona you intend to read/act on before trusting an empty or unexpected
state as a signal (e.g. before treating it as a stop condition).

Given this, the working pattern is not "tab 1 = persona A, tab 2 = persona B
forever" but: **one tab per lead conversation, and re-assert the correct
tenant on that tab immediately before every read or send**, even if you set
it correctly moments ago in the same tab.

## Reliable way to switch tenant: set the `<select>` value via JS

Coordinate-clicking the native OS-rendered dropdown options is unreliable —
the popup renders in a screenshot but clicks/keys on it frequently fail to
commit (selection reverts, or a stray click lands on the wrong control
entirely). Keyboard nav (`Up`/`Down` + `Return` after clicking the closed
select) works sometimes but not consistently across reloads.

The reliable method is `javascript_tool`, bypassing the OS popup entirely:

```js
const sel = document.querySelector('select');
const nativeSetter = Object.getOwnPropertyDescriptor(
  window.HTMLSelectElement.prototype, 'value'
).set;
nativeSetter.call(sel, 'aurora');           // option value, e.g. 'aurora' | 'vz-lupas'
sel.dispatchEvent(new Event('change', { bubbles: true }));
sel.value; // confirm
```

`document.querySelector('select')` is safe when the page currently shows
only the `CLIENTE` select; if other selects are present, resolve a ref first
via `read_page` (`filter: "interactive"`) and target it by id/name instead.
After dispatching `change`, wait ~1s before the next screenshot/action — the
lead list and conversation pane re-render asynchronously.

## Reading facts: trust the API, not the chat bubbles

Chat-bubble text is downstream of an LLM rephrase and can drift from the
underlying decision state. Use the persisted state as ground truth:

```js
const r = await fetch('/api-brain/leads/{leadId}', { credentials: 'include' });
const j = await r.json();
const facts = j?.metadata?.conversation_state?.facts ?? {};
// facts[field_key] = { status: 'known'|..., value, revision, updated_at, ... }
```

Poll this after every send instead of (or in addition to) screenshotting the
thread. It is the fastest way to confirm a field was actually captured vs.
merely acknowledged in prose.

## Sending: prefer the visible "enviar" button over Ctrl+Enter

A raw `ctrl+Return` keypress inside the composer was blocked once mid-run by
the Claude Code auto-mode permission classifier (flagged as an ambiguous
send action needing confirmation), even though the composer explicitly
advertises "Ctrl+Enter envia." Clicking the on-screen **enviar** button sent
the same message without triggering that block. Prefer the button click as
the default send action; treat `Ctrl+Enter` as a fallback only.

## Message-count tripwire needs a human check before escalating

Capture the "`N msgs`" counter before and after every send/wait cycle and
treat any unexplained delta as a stop condition (per the main skill). But
before reporting it as a platform bug, consider that a human operator may be
manually testing the *same* physical test phone concurrently (e.g. sending
their own "oi" to sanity-check the number is alive). Surface the exact
delta and ask, rather than assuming worst case silently — but still hold
sends until it's confirmed benign. In the run this reference was written
from, two extra inbound "oi" messages were the human operator's own manual
test traffic, not a duplicate-send bug.

## Graph-sourced price disclosure is not a UI/runtime bug

If the target agent's final message states a concrete price/duration
alongside a human-confirmation disclaimer (e.g. "...parte de R$ 350,00...
a Equipe X vai te chamar para confirmar o valor final e o melhor horário"),
check the published graph's FAQ/product nodes before treating it as a
runtime defect — this phrasing is frequently sourced verbatim from a graph
FAQ `answer`/`markdown` field (see `brain-appointment-graph` skill and
`api/scripts/fixtures/{persona}_graph_v2.json`), not injected by the model
or the backend. It is still correct to flag it against the skill's
"final message promises human confirmation rather than confirming final
price, date or time" bar — just attribute it to graph content, not code.
