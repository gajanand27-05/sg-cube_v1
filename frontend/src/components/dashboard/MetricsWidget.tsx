import { Activity } from 'lucide-react'
import { useMetricsStore } from '@/store'

export function MetricsWidget() {
  const metrics = useMetricsStore((s) => s.metrics)

  if (!metrics) {
    return (
      <div className="glass rounded-2xl flex flex-col p-5">
        <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
          <div className="flex items-center gap-2 tp-1">
            <Activity size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
            SYSTEM METRICS
          </div>
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-sgc-dim" />
            <span className="text-sgc-dim text-[10px] font-mono tracking-widest uppercase">STANDBY</span>
          </div>
        </div>

        <div className="flex-1 flex flex-col items-center justify-center gap-2 py-6 text-center">
          <Activity size={28} className="text-sgc-dim opacity-40 mb-2" />
          <span className="text-sgc-dim font-mono text-[11px] uppercase tracking-wider">Waiting for AI telemetry…</span>
          <span className="text-sgc-dim/60 font-mono text-[10px]">Backend metrics stream not connected</span>
        </div>
      </div>
    )
  }

  const rows: [string, string][] = [
    ['Tokens/s', metrics.tokens_per_second.toFixed(1)],
    ['Latency', `${metrics.latency_ms} ms`],
    ['Inference', `${metrics.inference_ms} ms`],
    ['Queue', String(metrics.queue_depth)],
    ['Tool Calls', String(metrics.tool_calls)],
  ]

  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Activity size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          SYSTEM METRICS
        </div>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-[#00ff41] shadow-[0_0_5px_#00ff41] animate-pulse" />
          <span className="text-[#00ff41] text-[10px] font-mono tracking-widest uppercase">REAL-TIME</span>
        </div>
      </div>

      <div className="flex flex-col gap-2 font-mono text-[10px] uppercase tracking-wider text-sgc-dim">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between border-b border-sgc-border pb-1">
            <span>{label}</span>
            <span className="text-sgc-bright">{value}</span>
          </div>
        ))}
        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Model</span>
          <span className="text-sgc-bright normal-case tracking-normal">{metrics.active_model}</span>
        </div>
      </div>
    </div>
  )
}
