import { useUiEvent } from "@/hooks/useUiEvents";

/** Model latency — honest label per handoff: this is provider latency
 *  (tokens in, tokens out), not perceived wake → first_audio_out. The
 *  number the owner cares about lives in TurnLatency and is not on this
 *  event, so the row says "Model" to keep it from being misread as voice. */
export function LatencyPanel() {
  const metrics = useUiEvent("ai_metrics");

  return (
    <div className="flex flex-col gap-3 min-h-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="hud-label">Model</span>
        <span className="font-mono text-2xl text-hud-text">
          {metrics === null ? (
            <span className="text-sm text-hud-text-dim">—</span>
          ) : (
            <span key={metrics.latency_ms} className="inline-block hud-crossfade">
              {metrics.latency_ms} ms
            </span>
          )}
        </span>
      </div>

      <div className="flex flex-col gap-1.5 min-w-0">
        {metrics === null ? (
          <span className="font-mono text-[10px] text-hud-text-dim">
            awaiting first turn
          </span>
        ) : (
          <>
            <MetricRow label="Inference" value={`${metrics.inference_ms} ms`} />
            <MetricRow label="Queue" value={String(metrics.queue_depth)} />
            <MetricRow label="Throughput" value={`${metrics.tokens_per_second}/s`} />
            <span className="text-[10px] font-mono text-hud-text-dim truncate">
              {metrics.active_model}
            </span>
          </>
        )}
      </div>
    </div>
  );
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
