import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { WsEvent } from '@/hooks/useWebSocket'
import { useNow } from '@/hooks/useNow'
import { Clock, Filter, ArrowUpRight, Pause, Play } from 'lucide-react'
import {
  EVENT_COLORS,
  DEFAULT_COLOR,
  DASH_MODULES,
  matchDashModule,
  summarizeEvent,
  eventDuration,
  isActiveEvent,
} from '@/lib/events'

interface Props {
  events: WsEvent[]
  onSelectEvent?: (event: WsEvent) => void
  selectedEventId?: string | null
}

const MAX_ROWS = 20

export function EventTimelineWidget({ events, onSelectEvent, selectedEventId }: Props) {
  const [filter, setFilter] = useState<(typeof DASH_MODULES)[number]>('All')
  const [paused, setPaused] = useState(false)
  const [frozen, setFrozen] = useState<WsEvent[] | null>(null)
  const now = useNow(1000)
  const scrollRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const source = paused ? (frozen ?? []) : events
  const filtered = source.filter((e) => matchDashModule(e.type, filter))
  const shown = filtered.slice(-MAX_ROWS)

  // Pause freezes a snapshot; resume returns to live.
  const togglePause = () => {
    if (paused) {
      setPaused(false)
      setFrozen(null)
    } else {
      setFrozen(events)
      setPaused(true)
    }
  }

  // Auto-scroll to newest (bottom) while live.
  useEffect(() => {
    if (paused) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [shown.length, paused])

  return (
    <div className="glass rounded-2xl flex flex-col p-5 min-h-[200px] flex-1">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Clock size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          LIVE TIMELINE
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={togglePause}
            className="flex items-center gap-1 text-[9px] font-mono tracking-widest uppercase text-sgc-dim hover:text-sgc-primary transition-colors"
            title={paused ? 'Resume live updates' : 'Pause live updates'}
          >
            {paused ? <Play size={11} /> : <Pause size={11} />}
            {paused ? 'Resume' : 'Pause'}
          </button>
          <button
            onClick={() => navigate('/inspector')}
            className="flex items-center gap-1 text-[9px] font-mono tracking-widest uppercase text-sgc-dim hover:text-sgc-primary transition-colors"
            title="Open System Inspector"
          >
            Inspector <ArrowUpRight size={11} />
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-3 overflow-x-auto custom-scrollbar pb-1">
        {DASH_MODULES.map((f) => {
          const count = events.filter((e) => matchDashModule(e.type, f)).length
          return (
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
              <span className="opacity-50">{count}</span>
            </button>
          )
        })}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-2 font-mono text-[10px] text-sgc-dim pr-1">
        {shown.length === 0 ? (
          <div className="text-center italic opacity-50 mt-4 flex items-center justify-center gap-2">
            <Filter size={12} /> No events match filter
          </div>
        ) : (
          shown.map((event) => {
            const colorClass = EVENT_COLORS[event.type] || DEFAULT_COLOR
            const isSelected = selectedEventId === event.id
            const textColor = colorClass.split(' ')[0]
            const borderColor = colorClass.split(' ')[1]
            const summary = summarizeEvent(event)
            const duration = eventDuration(event)
            const active = isActiveEvent(event, now)

            return (
              <div
                key={event.id}
                onClick={() => onSelectEvent?.(event)}
                className={`flex flex-col gap-0.5 border-l-2 pl-2 transition-all cursor-pointer ${
                  isSelected
                    ? `${borderColor} bg-white/5 py-1 -ml-2 pl-4 rounded-r`
                    : active
                      ? `${borderColor} bg-white/[0.04] -ml-2 pl-4 rounded-r`
                      : 'border-sgc-border hover:border-sgc-dim'
                }`}
                style={active && !isSelected ? { boxShadow: '0 0 10px -2px currentColor' } : undefined}
              >
                <div className="flex justify-between items-center opacity-80">
                  <span className={`text-[9px] ${textColor}`}>
                    {new Date(event.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })}
                  </span>
                  <span className="flex items-center gap-2">
                    {duration !== null && <span className="text-[9px] text-sgc-dim opacity-60">{duration}ms</span>}
                    {active && <span className="w-1.5 h-1.5 rounded-full bg-[#00ff41] shadow-[0_0_5px_#00ff41]" />}
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
  )
}
