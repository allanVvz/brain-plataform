// "open" is Evolution/Baileys' own vocabulary for a live session; "connected"
// covers other providers. Both mean the same thing to a viewer -- anywhere
// that shows connection state must treat them the same way, or different
// screens contradict each other over the exact same channel. Shared between
// the client portal (PortalContext.tsx re-exports this) and the internal
// dashboard so neither reimplements it.
const CONNECTED_STATES = new Set(["connected", "open"]);

export function isChannelConnected(status?: string | null) {
  return CONNECTED_STATES.has(String(status || "").toLowerCase());
}
