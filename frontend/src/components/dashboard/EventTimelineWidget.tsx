import { useState } from 'react'
import type { WsEvent } from '@/hooks/useWebSocket'
import { Clock, Filter } from 'lucide-react'

interface Props {
  events: WsEvent[]
  onSelectEvent?: (event: WsEvent) => void
  selectedEventId?: string | null
}

const EVENT_COLORS: Record<string, string> = {
  voice_detected: 'text-[#00ff41] border-[#00ff41]',
  speech_recognition: 'text-[#00ff41] border-[#00ff41]',
  memory_search: 'text-[#a855f7] border-[#a855f7]',
  tool_call: 'text-[#3b82f6] border-[#3b82f6]',
  vision_detected: 'text-[#f97316] border-[#f97316]',
  llm_reasoning: 'text-[#eab308] border-[#eab308]',
  error: 'text-[#ef4444] border-[#ef4444]'
}
const DEFAULT_COLOR = 'text-[#00aaff] border-[#00aaff]'

type FilterType = 'All' | 'Voice' | 'Memory' | 'Tool' | 'Vision' | 'LLM' | 'Error'

export function EventTimelineWidget({ events, onSelectEvent, selectedEventId }: Props) {
  const [filter, setFilter] = useState<FilterType>('All')

  const filteredEvents = events.filter(e => {
    if (filter === 'All') return true
    if (filter === 'Voice') return e.type.includes('voice') || e.type.includes('speech')
    if (filter === 'Memory') return e.type.includes('memory')
    if (filter === 'Tool') return e.type.includes('tool')
    if (filter === 'Vision') return e.type.includes('vision')
    if (filter === 'LLM') return e.type.includes('llm') || e.type.includes('reasoning')
    if (filter === 'Error') return e.type.includes('error')
    return true
  })

  // Show only last 20 events in the UI for performance, newest top
  const recentEvents = [...filteredEvents].reverse().slice(0, 20)

  return (
    <div className="glass rounded-2xl flex flex-col p-5 min-h-[200px] flex-1">
      <div className="flex justify-between items-center mb-3 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Clock size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          EVENT TIMELINE
        </div>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-[#00ff41] shadow-[0_0_5px_#00ff41] animate-pulse" />
        </div>
      </div>
      
      {/* Filters */}
      <div className="flex gap-2 mb-3 overflow-x-auto custom-scrollbar pb-1">
        {(['All', 'Voice', 'Memory', 'Tool', 'Vision', 'LLM', 'Error'] as FilterType[]).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-[9px] font-mono tracking-widest uppercase px-2 py-0.5 border rounded transition-colors ${
              filter === f 
                ? 'border-sgc-primary text-sgc-bright bg-sgc-primary/10' 
                : 'border-sgc-border text-sgc-dim hover:border-sgc-dim'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-3 font-mono text-[10px] text-sgc-dim pr-1">
        {recentEvents.length === 0 ? (
          <div className="text-center italic opacity-50 mt-4 flex items-center justify-center gap-2">
            <Filter size={12} /> No events match filter
          </div>
        ) : (
          recentEvents.map((event) => {
            const colorClass = EVENT_COLORS[event.type] || DEFAULT_COLOR
            const isSelected = selectedEventId === event.id
            const textColor = colorClass.split(' ')[0]
            const borderColor = colorClass.split(' ')[1]

            return (
              <div 
                key={event.id} 
                onClick={() => onSelectEvent?.(event)}
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
                  <span className="text-[9px] opacity-50">{event.id}</span>
                </div>
                <span className="text-sgc-bright capitalize tracking-wide">{event.type.replace(/_/g, ' ')}</span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
