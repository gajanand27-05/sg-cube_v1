import { useEffect, useRef, useState } from "react";
import type {
  UiEventEnvelope,
  UiEventPayloadMap,
  UiEventType,
} from "@/lib/uiEvents";

export type ConnectionState = "connecting" | "open" | "closed";

const BACKOFF_MS = [1000, 2000, 4000, 8000, 10000];

function resolveUrl(): string {
  const envUrl = (import.meta.env.VITE_WS_URL as string | undefined) ?? "";
  return envUrl.length > 0 ? envUrl : "ws://127.0.0.1:8001/ws/ui";
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
    openSocket();
  }, delay);
}

function openSocket() {
  if (ws) return;
  setConnectionState("connecting");
  let socket: WebSocket;
  try {
    socket = new WebSocket(resolveUrl());
  } catch {
    scheduleReconnect();
    return;
  }
  ws = socket;

  socket.onopen = () => {
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
    latest.set(envelope.type, envelope);
    const set = listeners.get(envelope.type);
    if (!set) return;
    for (const l of set) l(envelope);
  };

  socket.onerror = () => {
    // let onclose handle recovery
  };

  socket.onclose = () => {
    ws = null;
    setConnectionState("closed");
    scheduleReconnect();
  };
}

function ensureStarted() {
  if (started) return;
  started = true;
  openSocket();
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
