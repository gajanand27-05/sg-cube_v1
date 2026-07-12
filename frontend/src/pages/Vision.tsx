import { useEffect, useState } from 'react'
import { Camera, Radar } from 'lucide-react'
import { useVisionStore } from '@/store'
import { cn } from '@/lib/utils'

interface Observation {
  content: string
  app: string
  timestamp?: string
}

export function Vision() {
  const windows = useVisionStore((s) => s.windows)
  const activeWindow = useVisionStore((s) => s.activeWindow)
  const lastDescription = useVisionStore((s) => s.lastDescription)
  const objects = useVisionStore((s) => s.objects)
  const ocr = useVisionStore((s) => s.ocr)

  const [shotTs, setShotTs] = useState(Date.now())
  const [observations, setObservations] = useState<Observation[]>([])
  const [feedError, setFeedError] = useState(false)

  const active = activeWindow || windows[0] || null

  // Poll the live screenshot feed (backend returns a JPEG of the current screen).
  useEffect(() => {
    const tick = setInterval(() => setShotTs(Date.now()), 2500)
    return () => clearInterval(tick)
  }, [])

  // Poll recent observations from the visual memory store.
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const r = await fetch('/vision/observations?limit=15')
        if (!r.ok) return
        const d = await r.json()
        if (!alive) return
        setObservations(
          (d.observations ?? []).map((o: Record<string, unknown>) => ({
            content: String(o.content ?? ''),
            app: String(o.app ?? (o.metadata as Record<string, unknown> | undefined)?.app ?? 'Unknown'),
            timestamp: o.timestamp ? String(o.timestamp) : undefined,
          })),
        )
      } catch {
        /* ignore — feed simply stays empty */
      }
    }
    load()
    const t = setInterval(load, 4000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  return (
    <div className="h-full flex flex-col p-5 overflow-hidden">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Vision Module</h1>
        <span className={cn(
          "font-mono text-[11px] tracking-widest uppercase",
          active ? "text-[#00ff41]" : "text-sgc-dim",
        )}>
          {active ? 'Live' : 'Standby'}
        </span>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-5 overflow-hidden min-h-0">
        {/* Live feed */}
        <div className="lg:col-span-2 glass rounded-2xl flex flex-col p-5 overflow-hidden">
          <div className="flex justify-between items-center mb-3">
            <div className="flex items-center gap-2 tp-1">
              <Camera size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
              LIVE FEED
            </div>
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#00ff41] shadow-[0_0_5px_#00ff41] animate-pulse" />
              <span className="text-[#00ff41] text-[10px] font-mono tracking-widest uppercase">Streaming</span>
            </div>
          </div>
          <div className="relative flex-1 min-h-0 rounded-lg overflow-hidden border border-sgc-border bg-[#050a14] flex items-center justify-center">
            <img
              src={`/vision/screenshot?ts=${shotTs}`}
              alt="Live screen feed"
              className="w-full h-full object-contain"
              onError={() => setFeedError(true)}
            />
            {feedError && (
              <div className="absolute inset-0 flex items-center justify-center text-sgc-dim font-mono text-sm text-center px-6 leading-relaxed">
                Screen capture unavailable.<br />
                Start the backend vision loop to enable the live feed.
              </div>
            )}
          </div>
          {active && (
            <div className="mt-3 flex items-center gap-2 font-mono text-[11px]">
              <span className="text-sgc-dim uppercase tracking-wider">Active Window</span>
              <span className="text-sgc-bright">{active}</span>
            </div>
          )}
        </div>

        {/* Side panel: detections + observations */}
        <div className="flex flex-col gap-5 overflow-y-auto pr-1 custom-scrollbar">
          <div className="glass rounded-2xl flex flex-col p-5">
            <div className="flex items-center gap-2 tp-1 mb-3">
              <Radar size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
              DETECTED
            </div>
            {objects.length > 0 ? (
              <div className="flex flex-col gap-1.5">
                {objects.map((o, i) => (
                  <div key={i} className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-sgc-bright text-sm normal-case tracking-normal min-w-0">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#f97316] shrink-0" />
                      <span className="truncate">{o.label}</span>
                    </span>
                    <span className="text-sgc-dim text-[10px] font-mono shrink-0">{Math.round(o.confidence * 100)}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-sgc-dim text-sm font-mono">No objects detected</span>
            )}

            {ocr.length > 0 && (
              <div className="mt-3 flex flex-col gap-1.5">
                <div className="text-[10px] text-sgc-dim uppercase tracking-wider">OCR</div>
                <div className="flex flex-wrap gap-1.5">
                  {ocr.map((t, i) => (
                    <span key={i} className="text-[10px] font-mono text-sgc-bright bg-[#0a1526] border border-sgc-border px-1.5 py-0.5 rounded">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {lastDescription && (
            <div className="glass rounded-2xl flex flex-col p-5">
              <div className="text-[10px] text-sgc-dim uppercase tracking-wider mb-2">Description</div>
              <span className="text-sgc-bright text-sm normal-case tracking-normal leading-snug">{lastDescription}</span>
            </div>
          )}

          <div className="glass rounded-2xl flex flex-col p-5">
            <div className="text-[10px] text-sgc-dim uppercase tracking-wider mb-3">Recent Observations</div>
            <div className="flex flex-col gap-2">
              {observations.length === 0 ? (
                <span className="text-sgc-dim text-sm font-mono">No observations yet</span>
              ) : (
                observations.map((o, i) => (
                  <div key={i} className="flex flex-col gap-0.5 border-b border-sgc-border pb-2">
                    <span className="text-sgc-bright text-sm normal-case tracking-normal leading-snug truncate">{o.content}</span>
                    <span className="text-sgc-dim text-[10px] font-mono uppercase tracking-wider">
                      {o.app}{o.timestamp ? ` · ${new Date(o.timestamp).toLocaleTimeString()}` : ''}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
