import { Activity } from 'lucide-react'

export function MetricsWidget() {
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
