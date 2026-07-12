import { Camera } from 'lucide-react'
import { useVisionStore } from '@/store'
import { cn } from '@/lib/utils'

export function VisionModuleWidget() {
  const windows = useVisionStore((s) => s.windows)
  const activeWindow = useVisionStore((s) => s.activeWindow)
  const lastDescription = useVisionStore((s) => s.lastDescription)
  const active = activeWindow || windows[0] || null

  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Camera size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          VISION MODULE
        </div>
        <div className={cn(
          "text-[10px] font-mono tracking-widest uppercase",
          active ? "text-[#00ff41]" : "text-sgc-dim"
        )}>
          {active ? 'LIVE' : 'STANDBY'}
        </div>
      </div>

      {/* Radar sweep hero */}
      <div className="w-[120px] h-[80px] bg-[#050a14] border border-sgc-border rounded overflow-hidden relative shrink-0 mb-4">
        <svg viewBox="0 0 120 80" className="w-full h-full" style={{ filter: 'drop-shadow(0 0 5px rgba(249,115,22,0.55))' }}>
          <circle cx="60" cy="40" r="34" fill="none" strokeWidth="1.5" stroke="#f97316" strokeOpacity="0.3" />
          <circle cx="60" cy="40" r="22" fill="none" strokeWidth="1.5" stroke="#f97316" strokeOpacity="0.3" />
          <circle cx="60" cy="40" r="10" fill="none" strokeWidth="1.5" stroke="#f97316" strokeOpacity="0.3" />
          <line x1="60" y1="6" x2="60" y2="74" strokeWidth="1.5" stroke="#f97316" strokeOpacity="0.2" />
          <line x1="26" y1="40" x2="94" y2="40" strokeWidth="1.5" stroke="#f97316" strokeOpacity="0.2" />
          <path d="M60 40 L94 40 A34 34 0 0 1 76 14 Z" fill="#f97316" opacity="0.18"
            style={{ transformOrigin: '60px 40px', animation: 'radar-sweep 4s linear infinite' }} />
          <circle cx="74" cy="28" r="2" fill="#00ff41" className="animate-pulse" />
        </svg>
      </div>

      {/* Active window + description (real data only) */}
      <div className="flex flex-col gap-3 font-mono text-[10px] uppercase tracking-wider text-sgc-dim">
        <div className="flex flex-col gap-1">
          <span className="text-sgc-dim">Active Window</span>
          <span className="text-sgc-bright text-sm normal-case tracking-normal truncate">
            {active || 'No window focused'}
          </span>
        </div>
        <div className="flex flex-col gap-1 border-t border-sgc-border pt-2">
          <span className="text-sgc-dim">Description</span>
          <span className="text-sgc-bright text-sm normal-case tracking-normal leading-snug">
            {lastDescription || 'Awaiting vision stream…'}
          </span>
        </div>
      </div>
    </div>
  )
}
