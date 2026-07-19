import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { statusPillClass, statusToneClasses } from "@/components/Panel";
import {
  useUiConnectionState,
  useUiEvent,
  useUiEventCounter,
  useUiEventListener,
} from "@/hooks/useUiEvents";

type StatusTone = "success" | "warning" | "danger" | "cyan" | "muted";
type CoreStatus = { status: string; tone: StatusTone };

const OPERATIONAL_MS = 5_000;
const RETRY_WINDOW_MS = 3_000;
const GAVE_UP_WINDOW_MS = 3_000;
const LATENCY_HISTORY_CAP = 20;

export function useAICoreStatus(): CoreStatus {
  const connection = useUiConnectionState();
  const [lastMetricsAt, setLastMetricsAt] = useState<number | null>(null);
  const [lastMetricsModel, setLastMetricsModel] = useState<string | null>(null);
  const [lastRetryAt, setLastRetryAt] = useState<number | null>(null);
  const [lastGaveUpAt, setLastGaveUpAt] = useState<number | null>(null);
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
    const t = Date.now();
    if (p.action === "retry") setLastRetryAt(t);
    if (p.action === "fallback") setDegradedSinceModel(lastMetricsModel ?? "");
    if (p.action === "gave_up") setLastGaveUpAt(t);
  });

  return useMemo<CoreStatus>(() => {
    if (connection !== "open") {
      return { status: "Offline", tone: "danger" };
    }
    if (lastGaveUpAt !== null && now - lastGaveUpAt < GAVE_UP_WINDOW_MS) {
      return { status: "Offline", tone: "danger" };
    }
    if (degradedSinceModel !== null) {
      return { status: "Degraded", tone: "warning" };
    }
    if (lastRetryAt !== null && now - lastRetryAt < RETRY_WINDOW_MS) {
      return { status: "Retrying", tone: "warning" };
    }
    if (lastMetricsAt !== null && now - lastMetricsAt < OPERATIONAL_MS) {
      return { status: "Operational", tone: "success" };
    }
    if (lastMetricsAt === null) {
      return { status: "Standby", tone: "cyan" };
    }
    return { status: "Idle", tone: "cyan" };
  }, [
    connection,
    lastMetricsAt,
    lastRetryAt,
    lastGaveUpAt,
    degradedSinceModel,
    now,
  ]);
}

/** The AI Core header pill.
 *
 *  Exists so useAICoreStatus's 1s ticker lives HERE rather than in App. Called
 *  at the tree root it re-rendered every panel, the PCB backdrop (~1000 SVG
 *  nodes) and the r3f Canvas once per second to update one word.
 */
export function AICoreStatusPill() {
  const { status, tone } = useAICoreStatus();
  return (
    <span className={cn(statusPillClass, statusToneClasses[tone])}>{status}</span>
  );
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

  const [lastConfidence, setLastConfidence] = useState<number | null>(null);
  const [lastResponseAt, setLastResponseAt] = useState<number | null>(null);
  useUiEventListener("agent_completed", (p) => {
    setLastConfidence(p.confidence);
    setLastResponseAt(Date.now());
  });

  const [latencyHistory, setLatencyHistory] = useState<number[]>([]);
  useUiEventListener("ai_metrics", (p) => {
    setLatencyHistory((h) => {
      const next = h.concat(p.latency_ms);
      return next.length > LATENCY_HISTORY_CAP
        ? next.slice(-LATENCY_HISTORY_CAP)
        : next;
    });
  });

  // Local 1s ticker for the "X ago" refresh. Kept separate from the one
  // inside useAICoreStatus so the two hooks don't share state.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const tokPerSec =
    metrics === null ? null : metrics.tokens_per_second.toFixed(1);
  const latencyMs = metrics === null ? null : `${metrics.latency_ms}ms`;
  const inferMs = metrics === null ? null : `${metrics.inference_ms}ms`;
  const agoText =
    lastResponseAt === null ? null : formatAgo(now - lastResponseAt);
  const confidenceBarBg =
    lastConfidence === null
      ? ""
      : lastConfidence < 25
      ? "bg-hud-danger"
      : lastConfidence < 50
      ? "bg-hud-warning"
      : "bg-hud-cyan-glow";

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

      {/* Row 3.5 — Confidence */}
      <div className="flex items-center justify-between gap-3">
        <span className="hud-label">Confidence</span>
        <div className="flex items-center gap-3 justify-end">
          <span className="font-mono text-xs">
            {lastConfidence === null ? (
              <span className="text-hud-text-dim">—</span>
            ) : (
              <span
                key={lastConfidence}
                className="inline-block text-hud-text hud-crossfade"
              >
                {lastConfidence.toFixed(0)}%
              </span>
            )}
          </span>
          {lastConfidence !== null && (
            <div className="w-16 h-1 bg-hud-border-dim rounded-sm overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-sm transition-all duration-200 ease-out",
                  confidenceBarBg,
                )}
                style={{ width: `${Math.max(0, Math.min(100, lastConfidence))}%` }}
              />
            </div>
          )}
        </div>
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

      {/* Row 5 — Reasoning ticker (single-line footer, empty state em-dash) */}
      <div className="flex items-center gap-3 min-w-0">
        <span className="hud-label shrink-0">Reasoning</span>
        <span
          className="font-mono text-[10px] text-hud-text-dim truncate"
          title={lastReasoning?.reasoning ?? ""}
        >
          {lastReasoning === null || !lastReasoning.reasoning
            ? "—"
            : lastReasoning.reasoning}
        </span>
      </div>

      {/* Row 6 — Last response + latency sparkline (footer) */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <span className="hud-label shrink-0">Last Response</span>
          <span className="font-mono text-xs">
            {agoText === null ? (
              <span className="text-hud-text-dim">—</span>
            ) : (
              <span
                key={agoText}
                className="inline-block text-hud-text hud-crossfade"
              >
                {agoText}
              </span>
            )}
          </span>
        </div>
        {latencyHistory.length >= 2 && (
          <Sparkline data={latencyHistory} />
        )}
      </div>
    </div>
  );
}

function formatAgo(ms: number): string {
  const s = Math.max(0, ms / 1000);
  if (s < 60) return `${s.toFixed(1)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function Sparkline({ data }: { data: number[] }) {
  const w = 72;
  const h = 18;
  let min = data[0];
  let max = data[0];
  for (const v of data) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const range = max - min;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = range === 0 ? h / 2 : h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="text-hud-cyan opacity-80 shrink-0"
    >
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
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
      <div className="text-[10px] uppercase tracking-[0.15em] text-hud-text-dim">
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
        style={
          lit
            ? {
                boxShadow:
                  "0 0 12px rgba(34, 197, 94, 0.35), inset 0 0 6px rgba(34, 197, 94, 0.12)",
              }
            : undefined
        }
      >
        <span
          className={cn(
            "inline-block w-2 h-2 rounded-full",
            lit ? "text-hud-success animate-pulse-glow" : "text-hud-text-muted opacity-25",
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

