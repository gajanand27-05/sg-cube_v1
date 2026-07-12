import { useEffect, useMemo, useRef, useState } from 'react'
import { useSocketStore } from '@/store'
import type { WsEvent } from '@/hooks/useWebSocket'
import { useNow } from '@/hooks/useNow'
import { Search, ScrollText, Pause, Play, Trash2, Download, GitBranch, Filter as FilterIcon } from 'lucide-react'
import { InspectorPanel } from '@/components/dashboard/InspectorPanel'
import {
  EVENT_COLORS,
  DEFAULT_COLOR,
  INSPECTOR_MODULES,
  matchInspectorModule,
  summarizeEvent,
  eventDuration,
  isActiveEvent,
  buildTrace,
} from '@/lib/events'

function download(filename: string, content: string, mime = 'application/json') {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const MODULE_COLORS: Record<string, string> = {
  Voice: 'text-[#00ff41]',
  AI: 'text-[#eab308]',
  Memory: 'text-[#a855f7]',
  Vision: 'text-[#f97316]',
  Tools: 'text-[#3b82f6]',
  Errors: 'text-[#ef4444]',
  Warnings: 'text-[#eab308]',
  Info: 'text-[#00aaff]',
}

const fmtTime = (ts: string) =>
  new Date(ts).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })

export function Inspector() {
  const allEvents = useSocketStore((s) => s.events)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState<Set<string>>(new Set(INSPECTOR_MODULES))
  const [selected, setSelected] = useState<WsEvent | null>(null)
  const [paused, setPaused] = useState(false)
  const [frozen, setFrozen] = useState<WsEvent[] | null>(null)
  const [clearedAt, setClearedAt] = useState<number | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const now = useNow(1000)
  const scrollRef = useRef<HTMLDivElement>(null)

  const toggleModule = (m: string) =>
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(m)) next.delete(m)
      else next.add(m)
      return next
    })

  const togglePause = () => {
    if (paused) {
      setPaused(false)
      setFrozen(null)
    } else {
      setFrozen(allEvents)
      setPaused(true)
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const m of INSPECTOR_MODULES) {
      c[m] = allEvents.filter((e) => matchInspectorModule(e.type, m, levelOf(e))).length
    }
    return c
  }, [allEvents])

  const visible = useMemo(() => {
    const source = paused ? frozen ?? [] : allEvents
    const q = query.trim().toLowerCase()
    return source
      .filter((e) => {
        if (clearedAt != null && new Date(e.timestamp).getTime() < clearedAt) return false
        const lvl = levelOf(e)
        const mod = INSPECTOR_MODULES.find((m) => matchInspectorModule(e.type, m, lvl))
        return mod ? active.has(mod) : false
      })
      .filter((e) => {
        if (!q) return true
        const hay = `${e.type} ${summarizeEvent(e)} ${JSON.stringify(e.payload ?? {})}`.toLowerCase()
        return hay.includes(q)
      })
  }, [allEvents, frozen, paused, clearedAt, active, query])

  const trace = useMemo(
    () => (selected ? buildTrace(allEvents, selected) : []),
    [allEvents, selected],
  )

  // Auto-scroll to newest (bottom) while live.
  useEffect(() => {
    if (paused) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [visible.length, paused])

  const exportLogs = () =>
    download(
      `sg-cube-logs-${Date.now()}.txt`,
      visible.map((e) => `${fmtTime(e.timestamp)} ${e.type} ${summarizeEvent(e)} ${JSON.stringify(e.payload ?? {})}`).join('\n'),
      'text/plain',
    )
  const exportJson = () => download(`sg-cube-events-${Date.now()}.json`, JSON.stringify(visible, null, 2))
  const exportSession = () => download(`sg-cube-session-${Date.now()}.json`, JSON.stringify(allEvents, null, 2))
  const exportTrace = () =>
    selected && download(`sg-cube-trace-${selected.id}.json`, JSON.stringify(trace, null, 2))

  return (
    <div className="h-full flex flex-col p-5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">System Inspector</h1>
        <span className={`flex items-center gap-1.5 text-[10px] font-mono tracking-widest uppercase ${paused ? 'text-[#eab308]' : 'text-[#00ff41]'}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${paused ? 'bg-[#eab308]' : 'bg-[#00ff41] shadow-[0_0_5px_#00ff41] animate-pulse'}`} />
          {paused ? 'Paused' : 'Live'}
        </span>
        <div className="relative ml-auto w-72 max-w-[40%]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-sgc-dim" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search events, payloads, sources…"
            className="w-full bg-[#050a14] border border-sgc-border rounded-lg pl-9 pr-3 py-2 text-sm text-sgc-bright placeholder:text-sgc-dim font-mono focus:outline-none focus:border-sgc-primary/60"
          />
        </div>
      </div>

      <div className="flex-1 grid grid-cols-[200px_1fr_380px] gap-5 overflow-hidden min-h-0">
        {/* Filters */}
        <div className="glass rounded-2xl flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-sgc-border tp-1 shrink-0">
            <FilterIcon size={14} className="text-sgc-primary" /> FILTERS
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-2 flex flex-col gap-1">
            {INSPECTOR_MODULES.map((m) => {
              const on = active.has(m)
              const c = MODULE_COLORS[m]
              return (
                <button
                  key={m}
                  onClick={() => toggleModule(m)}
                  className={`flex items-center justify-between gap-2 text-[10px] font-mono tracking-widest uppercase px-2 py-1.5 rounded border transition-colors ${
                    on ? 'border-sgc-primary/50 text-sgc-bright bg-sgc-primary/10' : 'border-transparent text-sgc-dim hover:border-sgc-border'
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-sm ${on ? c : 'bg-sgc-border'}`} />
                    {m}
                  </span>
                  <span className="opacity-50">{counts[m] ?? 0}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Event Stream */}
        <div className="glass rounded-2xl flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-sgc-border shrink-0">
            <div className="flex items-center gap-2 tp-1">
              <ScrollText size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
              EVENT STREAM
              <span className="text-[10px] font-mono text-sgc-dim">{visible.length}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={togglePause}
                className="flex items-center gap-1 text-[9px] font-mono tracking-widest uppercase text-sgc-dim hover:text-sgc-primary transition-colors px-2 py-1 border border-sgc-border rounded"
              >
                {paused ? <Play size={11} /> : <Pause size={11} />}
                {paused ? 'Resume' : 'Pause'}
              </button>
              <button
                onClick={() => setClearedAt(Date.now())}
                className="flex items-center gap-1 text-[9px] font-mono tracking-widest uppercase text-sgc-dim hover:text-sgc-primary transition-colors px-2 py-1 border border-sgc-border rounded"
              >
                <Trash2 size={11} /> Clear
              </button>
              <div className="relative">
                <button
                  onClick={() => setMenuOpen((v) => !v)}
                  className="flex items-center gap-1 text-[9px] font-mono tracking-widest uppercase text-sgc-dim hover:text-sgc-primary transition-colors px-2 py-1 border border-sgc-border rounded"
                >
                  <Download size={11} /> Export
                </button>
                {menuOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                    <div className="absolute right-0 mt-1 z-20 w-40 glass rounded-lg border border-sgc-border py-1 text-[10px] font-mono">
                      {[
                        ['Export Session', exportSession],
                        ['Export Logs', exportLogs],
                        ['Export JSON', exportJson],
                        ['Export Trace', exportTrace],
                      ].map(([label, fn]) => (
                        <button
                          key={label as string}
                          disabled={label === 'Export Trace' && !selected}
                          onClick={() => { (fn as () => void)(); setMenuOpen(false) }}
                          className="w-full text-left px-3 py-1.5 hover:bg-white/5 text-sgc-bright disabled:opacity-30 disabled:hover:bg-transparent"
                        >
                          {label as string}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
          <div ref={scrollRef} className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-1.5 p-3 font-mono text-[10px] text-sgc-dim">
            {visible.length === 0 ? (
              <div className="text-center italic opacity-50 mt-4">No events match the current filters</div>
            ) : (
              visible.map((event) => {
                const colorClass = EVENT_COLORS[event.type] || DEFAULT_COLOR
                const isSelected = selected?.id === event.id
                const textColor = colorClass.split(' ')[0]
                const borderColor = colorClass.split(' ')[1]
                const summary = summarizeEvent(event)
                const duration = eventDuration(event)
                const activeEvt = isActiveEvent(event, now)
                return (
                  <div
                    key={event.id}
                    onClick={() => setSelected(event)}
                    className={`flex flex-col gap-0.5 border-l-2 pl-2 transition-all cursor-pointer ${
                      isSelected
                        ? `${borderColor} bg-white/5 py-1 -ml-2 pl-3 rounded-r`
                        : activeEvt
                          ? `${borderColor} bg-white/[0.04] -ml-2 pl-3 rounded-r`
                          : 'border-sgc-border hover:border-sgc-dim'
                    }`}
                  >
                    <div className="flex justify-between items-center opacity-80">
                      <span className={`text-[9px] ${textColor}`}>{fmtTime(event.timestamp)}</span>
                      <span className="flex items-center gap-2">
                        {duration !== null && <span className="text-[9px] text-sgc-dim opacity-60">{duration}ms</span>}
                        {activeEvt && <span className="w-1.5 h-1.5 rounded-full bg-[#00ff41] shadow-[0_0_5px_#00ff41]" />}
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

        {/* Details */}
        <div className="glass rounded-2xl flex flex-col overflow-hidden">
          {selected ? (
            <InspectorPanel
              event={selected}
              related={trace}
              onSelectRelated={setSelected}
              onClose={() => setSelected(null)}
            />
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-sgc-dim p-6 text-center">
              <GitBranch size={28} className="opacity-40" />
              <span className="text-sm font-mono">Select an event to inspect its payload, metrics, and related trace.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function levelOf(e: WsEvent): string | undefined {
  const l = (e.payload || {}).level
  return typeof l === 'string' ? l : undefined
}
