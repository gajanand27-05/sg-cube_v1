import { useUiEvent } from "@/hooks/useUiEvents";

/** Turn reliability readout.
 *
 *  Headline uses `agent_completed.confidence` — fires every turn, already
 *  cache-seeded, survives remount (the handoff's recommended fix for the
 *  T-panel-listener-state-lost-on-remount trap). The detailed metrics come
 *  from the `confidence` event when one has fired this session.
 */
export function ConfidencePanel() {
  const completed = useUiEvent("agent_completed");
  const conf = useUiEvent("confidence");

  const headline =
    completed === null || typeof completed.confidence !== "number"
      ? null
      : `${completed.confidence.toFixed(0)}%`;

  return (
    <div className="flex flex-col gap-3 min-h-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="hud-label">Confidence</span>
        <span className="font-mono text-2xl text-hud-cyan-glow">
          {headline ?? (
            <span className="text-sm text-hud-text-dim">—</span>
          )}
        </span>
      </div>

      <div className="flex flex-col gap-1.5 min-w-0">
        {conf === null ? (
          <span className="font-mono text-[10px] text-hud-text-dim">
            awaiting first turn
          </span>
        ) : (
          <>
            <MetricRow
              label="Tool success"
              value={fmtPct(conf.metric_tool_success_rate)}
            />
            <MetricRow
              label="Memory recall"
              value={fmtPct(conf.metric_memory_recall_pct)}
            />
            <MetricRow
              label="Avg response"
              value={fmtSec(conf.metric_avg_response_sec)}
            />
            <MetricRow
              label="Hallucination"
              value={`${conf.metric_hallucination_passed}/${conf.metric_hallucination_total}`}
            />
          </>
        )}
      </div>
    </div>
  );
}

function fmtPct(v: number): string {
  return typeof v === "number" ? `${v.toFixed(1)}%` : "—";
}

function fmtSec(v: number): string {
  return typeof v === "number" ? `${v.toFixed(1)}s` : "—";
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2 min-w-0">
      <span className="text-[10px] uppercase tracking-[0.15em] text-hud-text-dim truncate">
        {label}
      </span>
      <span className="font-mono text-xs text-hud-text shrink-0">{value}</span>
    </div>
  );
}
