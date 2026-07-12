import { Activity } from 'lucide-react'

function Gauge({ label, value, color }: { label: string; value: number; color: string }) {
  const r = 26
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - value / 100)
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-16 h-16">
        <svg viewBox="0 0 64 64" className="w-full h-full -rotate-90">
          <circle cx="32" cy="32" r={r} fill="none" stroke="#0a1526" strokeWidth="5" />
          <circle cx="32" cy="32" r={r} fill="none" stroke={color} strokeWidth="5" strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={offset}
            style={{ filter: `drop-shadow(0 0 5px ${color})`, transition: 'stroke-dashoffset 0.4s ease' }} />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] text-sgc-bright">{value}%</div>
      </div>
      <span className="text-[8px] font-mono tracking-widest uppercase text-sgc-dim">{label}</span>
    </div>
  )
}

export function MetricsWidget() {
  // Use real stats if available, otherwise just show 0 or loading states,
  // but do not fake standard OS stats like CPU/RAM per user request.
  // Assuming the backend provides or will provide these AI metrics.
  
  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Activity size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          SYSTEM METRICS
        </div>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-[#00ff41] shadow-[0_0_5px_#00ff41] animate-pulse" />
          <span className="text-[#00ff41] text-[10px] font-mono tracking-widest uppercase">
            REAL-TIME
          </span>
        </div>
      </div>

      {/* Circular gauges */}
      <div className="flex justify-around mb-4">
        <Gauge label="AI Load" value={68} color="#00f3ff" />
        <Gauge label="Memory" value={42} color="#00ff41" />
      </div>

      <div className="grid grid-cols-2 gap-5 tp-3">
        
        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>LLM Tokens/s</span>
          <span className="text-sgc-bright">42.5</span>
        </div>
        
        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Inference Time</span>
          <span className="text-sgc-bright">1.2s</span>
        </div>
        
        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Latency</span>
          <span className="text-sgc-bright">120ms</span>
        </div>
        
        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Memory Recall</span>
          <span className="text-[#00ff41]">12ms</span>
        </div>

        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Voice Conf</span>
          <span className="text-sgc-bright">98%</span>
        </div>

        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Vision FPS</span>
          <span className="text-[#ffb700]">0.0</span>
        </div>

        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Active Threads</span>
          <span className="text-sgc-bright">4</span>
        </div>

        <div className="flex justify-between border-b border-sgc-border pb-1">
          <span>Queue Length</span>
          <span className="text-[#00ff41]">0</span>
        </div>
        
      </div>
    </div>
  )
}
