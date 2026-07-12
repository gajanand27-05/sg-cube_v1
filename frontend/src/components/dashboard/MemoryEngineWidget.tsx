import { Database, Check } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useMemoryStore } from '@/store'

function useRelativeTime(ts: number | null): string | null {
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])
  if (!ts) return null
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s ago`
}

export function MemoryEngineWidget() {
  const lastHit = useMemoryStore((s) => s.lastHit)
  const lastHitAt = useMemoryStore((s) => s.lastHitAt)
  const hitCount = useMemoryStore((s) => s.hitCount)
  const hits = useMemoryStore((s) => s.hits)
  const rel = useRelativeTime(lastHitAt)

  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Database size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          MEMORY ENGINE
        </div>
        <div className="text-[#00aaff] text-[10px] font-mono tracking-widest uppercase">
          OPTIMIZED
        </div>
      </div>

      {/* Holographic cylinder */}
      <div className="flex justify-center">
        <div className="w-7 h-9 relative shrink-0">
          <svg viewBox="0 0 32 40" className="w-full h-full" style={{ filter: 'drop-shadow(0 0 5px rgba(0,255,65,0.55))' }}>
            <ellipse cx="16" cy="8" rx="13" ry="4" fill="none" strokeWidth="1.5" stroke="#00ff41" strokeOpacity="0.5" />
            <ellipse cx="16" cy="32" rx="13" ry="4" fill="none" strokeWidth="1.5" stroke="#00ff41" strokeOpacity="0.5" />
            <path d="M3 8 V32 A13 4 0 0 0 29 32 V8" fill="rgba(0,255,65,0.06)" strokeWidth="1.5" stroke="#00ff41" strokeOpacity="0.4" />
            <circle cx="16" cy="20" r="13" fill="none" strokeWidth="1.5" stroke="#00ff41" strokeOpacity="0.3" strokeDasharray="3 5"
              style={{ transformOrigin: '16px 20px', animation: 'spin 4s linear infinite' }} />
          </svg>
        </div>
      </div>

      {/* Recent Recall (real data only) */}
      <div className="mt-4 flex flex-col gap-2">
        <div className="text-[10px] text-sgc-dim uppercase tracking-wider">Recent Recall</div>
        {hits.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            {hits.map((h, i) => (
              <div key={i} className="flex items-start gap-2">
                <Check size={13} className="text-[#00ff41] mt-0.5 shrink-0" />
                <div className="flex flex-col min-w-0 flex-1">
                  <div className="flex justify-between gap-2">
                    <span className="text-sgc-bright text-sm truncate">{h.title}</span>
                    <span className="text-sgc-bright text-[10px] font-mono shrink-0">{Math.round(h.score * 100)}%</span>
                  </div>
                  <span className="text-sgc-dim text-[9px] font-mono uppercase tracking-wider">{h.source}</span>
                </div>
              </div>
            ))}
          </div>
        ) : lastHit ? (
          <div className="flex items-start gap-2">
            <Check size={14} className="text-[#00ff41] mt-0.5 shrink-0" />
            <div className="flex flex-col min-w-0">
              <span className="text-sgc-bright text-sm truncate">"{lastHit}"</span>
              <span className="text-sgc-dim text-[10px] font-mono">{rel ?? 'just now'}</span>
            </div>
          </div>
        ) : (
          <span className="text-sgc-dim text-sm font-mono">No recalls yet</span>
        )}
      </div>

      {/* Recalls this session (real count) */}
      <div className="mt-4 pt-3 border-t border-sgc-border font-mono text-[10px] uppercase tracking-wider">
        <div className="flex justify-between mb-1.5">
          <span className="text-sgc-dim">Recalls (session)</span>
          <span className="text-sgc-bright">{hitCount}</span>
        </div>
      </div>
    </div>
  )
}
