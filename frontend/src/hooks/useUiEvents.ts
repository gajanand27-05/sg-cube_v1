import { useEffect, useRef, useState } from "react";
import type {
  UiEventEnvelope,
  UiEventPayloadMap,
  UiEventType,
} from "@/lib/uiEvents";

export type ConnectionState = "connecting" | "open" | "closed";

const BACKOFF_MS = [1000, 2000, 4000, 8000, 10000];

const DEV_SERVER_PORT = "5173";
const DEV_BACKEND = "127.0.0.1:8001";

/** Where the backend is. When the backend serves this page (the installed
 *  app, on whatever port it picked) that is simply this page's host; from the
 *  Vite dev server it is the dev backend. Exported for tests. */
export function backendBase(
  loc: { protocol: string; host: string; port: string } | null =
    typeof window === "undefined" ? null : window.location,
): { http: string; ws: string } {
  const envUrl = (import.meta.env.VITE_WS_URL as string | undefined) ?? "";
  if (envUrl.length > 0) {
    const u = new URL(envUrl);
    const http = `${u.protocol === "wss:" ? "https" : "http"}://${u.host}`;
    return { http, ws: `${u.protocol}//${u.host}` };
  }
  if (!loc || loc.port === DEV_SERVER_PORT) {
    return { http: `http://${DEV_BACKEND}`, ws: `ws://${DEV_BACKEND}` };
  }
  const secure = loc.protocol === "https:";
  return { http: `${secure ? "https" : "http"}://${loc.host}`, ws: `${secure ? "wss" : "ws"}://${loc.host}` };
}

// The socket requires this process's session token (backend/server/session.py).
// Fetched from /api/session, which only this app's own pages can read, and
// re-fetched when the server rejects it as stale (close code 4401 — e.g. the
// backend restarted and minted a new one).
let sessionToken: string | null = null;

async function fetchSessionToken(): Promise<string | null> {
  try {
    const r = await fetch(`${backendBase().http}/api/session`, { cache: "no-store" });
    if (!r.ok) return null;
    const body = (await r.json()) as { token?: unknown };
    return typeof body.token === "string" ? body.token : null;
  } catch {
    return null;
  }
}

function resolveUrl(token: string): string {
  return `${backendBase().ws}/ws/ui?token=${encodeURIComponent(token)}`;
}

// Fields each consumer actually dereferences, and the type it assumes. Guards
// the seam where untrusted JSON becomes typed state: without this a renamed or
// nulled backend field ships a TypeError straight into render.
//
// Only fields the UI touches are listed — this is a crash guard, not a schema.
const REQUIRED_FIELDS: Record<UiEventType, Record<string, "number" | "string" | "boolean">> = {
  ai_metrics: {
    tokens_per_second: "number",
    latency_ms: "number",
    inference_ms: "number",
    active_model: "string",
  },
  wake_heard: { peak: "number" },
  // Nothing dereferenced unconditionally; listed so the Record type is total
  // (its absence failed `tsc -b`, i.e. `npm run build`).
  followup_expired: {},
  intent_resolved: { source_layer: "string" },
  agent_thinking: { agent_name: "string", is_thinking: "boolean" },
  agent_reasoning: { reasoning: "string" },
  agent_completed: { confidence: "number" },
  provider_degraded: { action: "string" },
  // hits/total_entries are nullable by contract, so they can't be required
  // here — MemoryEnginePanel treats both as optional.
  memory_hit: { query: "string", results_count: "number" },
  memory_write_failed: { collection: "string", reason: "string" },
  // windows/objects/ocr are nullable by contract, so they can't be required
  // here — consumers treat all three as optional.
  vision_update: { description: "string" },
  stt_partial: { text: "string" },
  token_stream: { full_content: "string" },
  confidence: { metric_tool_success_rate: "number", metric_memory_recall_pct: "number" },
  tool_started: { tool_name: "string" },
  tool_finished: { tool_name: "string", status: "string" },
  confirmation_request: {
    id: "string", digest: "string", tool: "string", prompt: "string",
    critical: "boolean", expires_in_s: "number",
  },
  confirmation_resolved: { id: "string", outcome: "string" },
  system_stats: {
    cpu_percent: "number",
    memory_percent: "number",
    net_down_bps: "number",
  },
};

/** Exported for tests only — this is the gate that silently DROPS events, so
 *  it is the one piece of logic here that most needs asserting. */
export function isValidPayload(type: string, payload: unknown): boolean {
  const required = REQUIRED_FIELDS[type as UiEventType];
  // Unknown types pass through untouched — the UI never reads them, and
  // dropping them would silently break any future consumer.
  if (!required) return true;
  if (typeof payload !== "object" || payload === null) return false;
  const p = payload as Record<string, unknown>;
  for (const [field, kind] of Object.entries(required)) {
    // NaN would pass typeof but breaks .toFixed output.
    if (kind === "number" && !Number.isFinite(p[field])) return false;
    if (kind !== "number" && typeof p[field] !== kind) return false;
  }
  return true;
}

const warned = new Set<string>();
function warnOnce(type: string) {
  if (warned.has(type)) return;
  warned.add(type);
  console.warn(
    `[useUiEvents] dropping malformed "${type}" payload; ` +
      `UI stays on its empty state. Further warnings for this type suppressed.`,
  );
}

type PayloadListener<T extends UiEventType> = (
  envelope: UiEventEnvelope<T>,
) => void;

type AnyListener = (envelope: UiEventEnvelope) => void;

const listeners = new Map<UiEventType, Set<AnyListener>>();
const latest = new Map<UiEventType, UiEventEnvelope>();

let ws: WebSocket | null = null;
let connectionState: ConnectionState = "closed";
let backoffIndex = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let started = false;

const connectionListeners = new Set<(s: ConnectionState) => void>();

function setConnectionState(next: ConnectionState) {
  if (connectionState === next) return;
  connectionState = next;
  for (const l of connectionListeners) l(next);
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = BACKOFF_MS[Math.min(backoffIndex, BACKOFF_MS.length - 1)];
  backoffIndex += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void openSocket();
  }, delay);
}

let opening = false;

async function openSocket() {
  if (ws || opening) return;
  opening = true;
  setConnectionState("connecting");
  try {
    if (!sessionToken) sessionToken = await fetchSessionToken();
    if (!sessionToken) {
      setConnectionState("closed");
      scheduleReconnect();
      return;
    }
    let socket: WebSocket;
    try {
      socket = new WebSocket(resolveUrl(sessionToken));
    } catch {
      scheduleReconnect();
      return;
    }
    ws = socket;
    attach(socket);
  } finally {
    opening = false;
  }
}

/** Send a JSON message to the backend (e.g. a confirmation answer).
 *  Returns false when there is no open socket to send it on. */
export function sendUiMessage(message: Record<string, unknown>): boolean {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(message));
  return true;
}

function attach(socket: WebSocket) {
  let opened = false;

  socket.onopen = () => {
    opened = true;
    backoffIndex = 0;
    setConnectionState("open");
  };

  socket.onmessage = (ev) => {
    let envelope: UiEventEnvelope;
    try {
      envelope = JSON.parse(ev.data) as UiEventEnvelope;
    } catch {
      return;
    }
    if (!envelope || typeof envelope.type !== "string") return;
    if (!isValidPayload(envelope.type, envelope.payload)) {
      warnOnce(envelope.type);
      return;
    }
    latest.set(envelope.type, envelope);
    const set = listeners.get(envelope.type);
    if (!set) return;
    for (const l of set) l(envelope);
  };

  socket.onerror = () => {
    // let onclose handle recovery
  };

  socket.onclose = (ev) => {
    ws = null;
    // 4401: our token is stale (the backend restarted). Fetch a fresh one —
    // and likewise if the socket never opened at all, since a rejected
    // handshake can surface as a bare 1006 depending on the browser.
    if (ev.code === 4401 || !opened) sessionToken = null;
    setConnectionState("closed");
    scheduleReconnect();
  };
}

function ensureStarted() {
  if (started) return;
  started = true;
  void openSocket();
}

function subscribe<T extends UiEventType>(
  type: T,
  listener: PayloadListener<T>,
): () => void {
  ensureStarted();
  let set = listeners.get(type);
  if (!set) {
    set = new Set();
    listeners.set(type, set);
  }
  const wrapped = listener as unknown as AnyListener;
  set.add(wrapped);
  return () => {
    set!.delete(wrapped);
  };
}

// Vite HMR: close the socket when this module is replaced so we don't
// leak duplicate connections across hot-reloads during dev.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    const s = ws;
    ws = null;
    started = false;
    if (s) {
      s.onopen = null;
      s.onmessage = null;
      s.onerror = null;
      s.onclose = null;
      try {
        s.close();
      } catch {
        /* ignore */
      }
    }
  });
}

export function useUiEvent<T extends UiEventType>(
  type: T,
): UiEventPayloadMap[T] | null {
  const seed = latest.get(type) as UiEventEnvelope<T> | undefined;
  const [payload, setPayload] = useState<UiEventPayloadMap[T] | null>(
    seed ? seed.payload : null,
  );
  useEffect(() => {
    const cached = latest.get(type) as UiEventEnvelope<T> | undefined;
    if (cached) setPayload(cached.payload);
    return subscribe<T>(type, (env) => setPayload(env.payload));
  }, [type]);
  return payload;
}

/** Same seeding-from-latest contract as useUiEvent, but keeps the whole
 *  envelope so consumers get the server-side timestamp useUiEvent drops.
 *  Seeds from the module cache without replaying through subscribe(), so
 *  useUiEventCounter is never inflated by a remount — T-panel-listener-
 *  state-lost-on-remount fix direction. */
export function useUiEventEnvelope<T extends UiEventType>(
  type: T,
): UiEventEnvelope<T> | null {
  const seed = latest.get(type) as UiEventEnvelope<T> | undefined;
  const [env, setEnv] = useState<UiEventEnvelope<T> | null>(seed ?? null);
  useEffect(() => {
    const cached = latest.get(type) as UiEventEnvelope<T> | undefined;
    if (cached) setEnv(cached);
    return subscribe<T>(type, (e) => setEnv(e));
  }, [type]);
  return env;
}

export function useUiEventListener<T extends UiEventType>(
  type: T,
  handler: (payload: UiEventPayloadMap[T], envelope: UiEventEnvelope<T>) => void,
): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    return subscribe<T>(type, (env) => ref.current(env.payload, env));
  }, [type]);
}

export function useUiEventCounter<T extends UiEventType>(
  type: T,
  predicate?: (payload: UiEventPayloadMap[T]) => boolean,
): number {
  const [count, setCount] = useState(0);
  const predicateRef = useRef(predicate);
  predicateRef.current = predicate;
  useEffect(() => {
    return subscribe<T>(type, (env) => {
      const p = predicateRef.current;
      if (!p || p(env.payload)) setCount((c) => c + 1);
    });
  }, [type]);
  return count;
}

export function useUiConnectionState(): ConnectionState {
  const [state, setState] = useState<ConnectionState>(() => {
    ensureStarted();
    return connectionState;
  });
  useEffect(() => {
    ensureStarted();
    setState(connectionState);
    const l = (s: ConnectionState) => setState(s);
    connectionListeners.add(l);
    return () => {
      connectionListeners.delete(l);
    };
  }, []);
  return state;
}
