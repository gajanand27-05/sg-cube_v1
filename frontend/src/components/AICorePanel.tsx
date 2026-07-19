import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import {
  AGENT_ORDER,
  AGENT_SHORT,
  type AgentName,
} from "@/lib/uiEvents";
import {
  useUiConnectionState,
  useUiEvent,
  useUiEventCounter,
  useUiEventListener,
} from "@/hooks/useUiEvents";

type StatusTone = "success" | "warning" | "danger" | "cyan" | "muted";
type CoreStatus = { status: string; tone: StatusTone };

const OFFLINE_MS = 30_000;
const OPERATIONAL_MS = 5_000;
const RETRY_WINDOW_MS = 3_000;
const FLASH_MS = 400;

export function useAICoreStatus(): CoreStatus {
  const connection = useUiConnectionState();
  const [lastMetricsAt, setLastMetricsAt] = useState<number | null>(null);
  const [lastMetricsModel, setLastMetricsModel] = useState<string | null>(null);
  const [lastRetryAt, setLastRetryAt] = useState<number | null>(null);
  const [degradedSinceModel, setDegradedSinceModel] = useState<string | null>(
    null,
  );
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useUiEventListener("ai_metrics", (p) => {
    setLastMetricsAt(Date.now());
    setLastMetricsModel(p.active_model);
    if (degradedSinceModel !== null && p.active_model !== degradedSinceModel) {
      setDegradedSinceModel(null);
    }
  });

  useUiEventListener("provider_degraded", (p) => {
    if (p.action === "retry") setLastRetryAt(Date.now());
    if (p.action === "fallback") setDegradedSinceModel(lastMetricsModel ?? "");
  });

  return useMemo<CoreStatus>(() => {
    if (
      connection === "closed" ||
      lastMetricsAt === null ||
      now - lastMetricsAt > OFFLINE_MS
    ) {
      return { status: "Offline", tone: "danger" };
    }
    if (degradedSinceModel !== null) {
      return { status: "Degraded", tone: "warning" };
    }
    if (lastRetryAt !== null && now - lastRetryAt < RETRY_WINDOW_MS) {
      return { status: "Retrying", tone: "warning" };
    }
    if (now - lastMetricsAt < OPERATIONAL_MS) {
      return { status: "Operational", tone: "success" };
    }
    return { status: "Operational", tone: "success" };
  }, [connection, lastMetricsAt, lastRetryAt, degradedSinceModel, now]);
}

export function AICorePanel() {
  const metrics = useUiEvent("ai_metrics");
  const lastIntent = useUiEvent("intent_resolved");
  const lastReasoning = useUiEvent("agent_reasoning");

  const cacheCount = useUiEventCounter(
    "intent_resolved",
    (p) => p.source_layer === "cache",
  );
  const ruleCount = useUiEventCounter(
    "intent_resolved",
    (p) => p.source_layer === "rule",
  );
  const llmCount = useUiEventCounter(
    "intent_resolved",
    (p) => p.source_layer === "llm",
  );

  const [fallbackTarget, setFallbackTarget] = useState<string | null>(null);
  useUiEventListener("provider_degraded", (p) => {
    if (p.action === "fallback" && p.fallback) setFallbackTarget(p.fallback);
  });

  const [thinking, setThinking] = useState<Record<string, boolean>>({});
  useUiEventListener("agent_thinking", (p) => {
    setThinking((prev) => ({ ...prev, [p.agent_name]: p.is_thinking }));
  });

  const [flash, setFlash] = useState<Record<string, "green" | "red" | null>>(
    {},
  );
  const flashTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  useUiEventListener("agent_completed", (p) => {
    const color =
      p.status === "failed" ? "red" : p.status === "completed" || p.status === "verified" ? "green" : null;
    if (!color) return;
    const name = p.agent_name;
    setFlash((prev) => ({ ...prev, [name]: color }));
    const existing = flashTimers.current[name];
    if (existing) clearTimeout(existing);
    flashTimers.current[name] = setTimeout(() => {
      setFlash((prev) => ({ ...prev, [name]: null }));
    }, FLASH_MS);
  });

  useEffect(() => {
    return () => {
      for (const t of Object.values(flashTimers.current)) clearTimeout(t);
    };
  }, []);

  const tokPerSec =
    metrics === null ? null : metrics.tokens_per_second.toFixed(1);
  const latencyMs = metrics === null ? null : `${metrics.latency_ms}ms`;
  const inferMs = metrics === null ? null : `${metrics.inference_ms}ms`;

  return (
    <div className="flex flex-col gap-4">
      {/* Row 2 — Active model */}
      <div className="flex items-center justify-between gap-3">
        <span className="hud-label">Model</span>
        <div className="flex items-center gap-2 min-w-0 justify-end">
          <span className="font-mono text-xs text-hud-text truncate">
            {metrics === null ? "—" : metrics.active_model}
          </span>
          {fallbackTarget && (
            <span className="font-mono text-xs text-hud-cyan-dim truncate">
              → {fallbackTarget}
            </span>
          )}
        </div>
      </div>

      {/* Row 3 — Three-stat row */}
      <div className="grid grid-cols-3 gap-3">
        <MetricStat label="Tok/s" value={tokPerSec} />
        <MetricStat label="Latency" value={latencyMs} tone="cyan" />
        <MetricStat label="Infer" value={inferMs} />
      </div>

      {/* Row 4 — Router tier LED strip */}
      <div>
        <div className="grid grid-cols-3 gap-2">
          <TierPill
            label="Cache"
            lit={lastIntent?.source_layer === "cache"}
            count={cacheCount}
          />
          <TierPill
            label="Rule"
            lit={lastIntent?.source_layer === "rule"}
            count={ruleCount}
          />
          <TierPill
            label="LLM"
            lit={lastIntent?.source_layer === "llm"}
            count={llmCount}
          />
        </div>
      </div>

      {/* Row 5 — Agent pipeline + reasoning ticker */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          {AGENT_ORDER.map((name) => (
            <AgentDot
              key={name}
              name={name}
              thinking={thinking[name] === true}
              flash={flash[name] ?? null}
            />
          ))}
        </div>
        <div
          className="font-mono text-[10px] text-hud-text-dim truncate"
          title={lastReasoning?.reasoning ?? ""}
        >
          {lastReasoning === null || !lastReasoning.reasoning
            ? "—"
            : lastReasoning.reasoning}
        </div>
      </div>
    </div>
  );
}

function MetricStat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | null;
  tone?: "default" | "cyan";
}) {
  return (
    <div className="leading-tight">
      <div className="text-[9px] uppercase tracking-[0.15em] text-hud-text-muted">
        {label}
      </div>
      <div
        className={cn(
          "text-sm font-mono",
          tone === "cyan" ? "text-hud-cyan-glow" : "text-hud-text",
        )}
      >
        {value === null ? (
          <span className="text-hud-text-dim">—</span>
        ) : (
          <span key={value} className="inline-block hud-crossfade">
            {value}
          </span>
        )}
      </div>
    </div>
  );
}

function TierPill({
  label,
  lit,
  count,
}: {
  label: string;
  lit: boolean;
  count: number;
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div
        className={cn(
          "flex items-center justify-center gap-1.5 w-full py-1 rounded-sm border",
          lit
            ? "border-hud-cyan text-hud-cyan-glow"
            : "border-hud-border-dim text-hud-text-dim",
        )}
      >
        <span
          className={cn(
            "inline-block w-2 h-2 rounded-full",
            lit ? "text-hud-cyan-glow animate-pulse-glow" : "text-hud-text-muted opacity-25",
          )}
          style={{
            backgroundColor: "currentColor",
            boxShadow: lit ? "0 0 8px currentColor" : "none",
          }}
        />
        <span className="text-[10px] uppercase tracking-[0.15em] font-semibold">
          {label}
        </span>
      </div>
      <div className="font-mono text-[10px] text-hud-text-dim">{count}</div>
    </div>
  );
}

function AgentDot({
  name,
  thinking,
  flash,
}: {
  name: AgentName;
  thinking: boolean;
  flash: "green" | "red" | null;
}) {
  const active = thinking || flash !== null;
  const tone =
    flash === "green"
      ? "text-hud-success"
      : flash === "red"
      ? "text-hud-danger"
      : thinking
      ? "text-hud-cyan-glow"
      : "text-hud-cyan-dim";
  return (
    <div className="flex flex-col items-center gap-1">
      <span
        className={cn(
          "inline-block w-2 h-2 rounded-full",
          tone,
          thinking && "animate-pulse-glow",
          !active && "opacity-25",
        )}
        style={{
          backgroundColor: "currentColor",
          boxShadow: active ? "0 0 8px currentColor" : "none",
        }}
      />
      <span
        className={cn(
          "text-[9px] uppercase tracking-[0.15em] font-mono",
          active ? "text-hud-text-dim" : "text-hud-text-muted",
        )}
      >
        {AGENT_SHORT[name]}
      </span>
    </div>
  );
}
