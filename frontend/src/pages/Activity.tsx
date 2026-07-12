import { useMemo, useState } from 'react'
import { useSocketStore } from '@/store'
import type { WsEvent } from '@/hooks/useWebSocket'
import { Search, Activity as ActivityIcon, ArrowUpRight } from 'lucide-react'
import { InspectorPanel } from '@/components/dashboard/InspectorPanel'
import {
  EVENT_COLORS,
  DEFAULT_COLOR,
  MODULES,
  matchModule,
  summarizeEvent,
  eventDuration,
} from '@/lib/events'

export function Activity() {
  const events = useSocketStore((s) => s.events)
  const [filter, setFilter] = useState<(typeof MODULES)[number]>('All')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<WsEvent | null>(null)

  const counts = useMemo(() => {
    const c: Record<string, number> = { All: events.length }
    for (const m of MODULES) if (m !== 'All') c[m] = events.filter((e) => matchModule(e.type, m)).length
    return c
  }, [events])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return events
      .filter((e) => matchModule(e.type, filter))
      .filter((e) => {
        if (!q) return true
        const hay = `${e.type} ${summarizeEvent(e)} ${JSON.stringify(e.payload ?? {})}`.toLowerCase()
        return hay.includes(q)
      })
      .slice()
      .reverse()
  }, [events, filter, query])

  return (
    <div className="h-full flex flex-col p-5 overflow-hidden">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Activity Inspector</h1>
        <span className="flex items-center gap-1.5 text-[10px] font-mono tracking-widest uppercase text-[#00ff41]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#00ff41] shadow-[0_0_5px_#00ff41] animate-pulse" />
          Live · {events.length} events
        </span>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-3 mb-4 shrink-0">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-sgc-dim" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search events, payloads, sources…"
            className="w-full bg-[#050a14] border border-sgc-border rounded-lg pl-9 pr-3 py-2 text-sm text-sgc-bright placeholder:text-sgc-dim font-mono focus:outline-none focus:border-sgc-primary/60"
          />
        </div>
        <div className="flex gap-2 overflow-x-auto custom-scrollbar pb-1">
          {MODULES.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`text-[9px] font-mono tracking-widest uppercase px-2 py-0.5 border rounded transition-colors flex items-center gap-1 ${
                filter === f
                  ? 'border-sgc-primary text-sgc-bright bg-sgc-primary/10'
                  : 'border-sgc-border text-sgc-dim hover:border-sgc-dim'
              }`}
            >
              {f}
              <span className="opacity-50">{counts[f] ?? 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-5 overflow-hidden min-h-0">
        {/* Event log */}
        <div className="lg:col-span-2 glass rounded-2xl flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-sgc-border shrink-0">
            <div className="flex items-center gap-2 tp-1">
              <ActivityIcon size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
              EVENT LOG
            </div>
            <span className="text-[10px] font-mono text-sgc-dim">{visible.length} shown</span>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-2 p-3 font-mono text-[10px] text-sgc-dim">
            {visible.length === 0 ? (
              <div className="text-center italic opacity-50 mt-4">No events match the current filter</div>
            ) : (
              visible.map((event) => {
                const colorClass = EVENT_COLORS[event.type] || DEFAULT_COLOR
                const isSelected = selected?.id === event.id
                const textColor = colorClass.split(' ')[0]
                const borderColor = colorClass.split(' ')[1]
                const summary = summarizeEvent(event)
                const duration = eventDuration(event)
                return (
                  <div
                    key={event.id}
                    onClick={() => setSelected(event)}
                    className={`flex flex-col gap-0.5 border-l-2 pl-2 transition-all cursor-pointer ${
                      isSelected
                        ? `${borderColor} bg-white/5 py-1 -ml-2 pl-4 rounded-r`
                        : 'border-sgc-border hover:border-sgc-dim'
                    }`}
                  >
                    <div className="flex justify-between items-center opacity-80">
                      <span className={`text-[9px] ${textColor}`}>
                        {new Date(event.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })}
                      </span>
                      <span className="flex items-center gap-2">
                        {duration !== null && <span className="text-[9px] text-sgc-dim opacity-60">{duration}ms</span>}
                        <span className="text-[9px] opacity-50">{event.id}</span>
                      </span>
                    </div>
                    <span className="text-sgc-bright capitalize tracking-wide">{event.type.replace(/_/g, ' ')}</span>
                    {summary && <span className="text-sgc-dim text-[9px] normal-case tracking-normal truncate">{summary}</span>}
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Detail drawer */}
        <div className="hidden lg:flex flex-col overflow-hidden">
          {selected ? (
            <InspectorPanel event={selected} onClose={() => setSelected(null)} />
          ) : (
            <div className="glass rounded-2xl flex-1 flex flex-col items-center justify-center gap-2 text-sgc-dim p-6 text-center">
              <ArrowUpRight size={28} className="opacity-40" />
              <span className="text-sm font-mono">Select an event to inspect its full payload, latency, and source.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
