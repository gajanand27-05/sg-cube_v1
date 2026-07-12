import { useState } from 'react'
import type { WsEvent } from '@/hooks/useWebSocket'
import { X, ChevronDown, ChevronRight, Activity, GitBranch } from 'lucide-react'
import { EVENT_COLORS, DEFAULT_COLOR, eventMetrics } from '@/lib/events'

interface Props {
  event: WsEvent
  onClose: () => void
  related?: WsEvent[]
  onSelectRelated?: (e: WsEvent) => void
}

export function InspectorPanel({ event, onClose, related, onSelectRelated }: Props) {
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    Request: true,
    Response: true,
    Metrics: true,
    Payload: true,
    AdditionalData: false
  })

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }))
  }

  const colorClass = EVENT_COLORS[event.type] || 'text-[#00aaff]'

  // Try to parse out standard fields from payload, otherwise fallback to generic
  const payload = event.payload || {}
  const duration = payload.duration_ms || payload.latency_ms || payload.latency || payload.duration
  const status = payload.status || (event.type === 'error' ? 'Failed' : 'Success')
  const funcName = payload.function_name || payload.tool || payload.action
  
  const hasRequest = 'request' in payload
  const hasResponse = 'response' in payload
  const hasMetrics = 'metrics' in payload

  const renderJson = (data: any) => (
    <pre className="font-mono text-[9px] text-sgc-bright bg-[#030816] p-2 rounded border border-[#0a1526] overflow-x-auto whitespace-pre-wrap">
      {JSON.stringify(data, null, 2)}
    </pre>
  )

  const Section = ({ title, data }: { title: string, data: any }) => {
    // Hide empty objects
    if (!data || (typeof data === 'object' && Object.keys(data).length === 0)) return null
    const isExpanded = expandedSections[title.replace(/\s+/g, '')]
    return (
      <div className="flex flex-col gap-1.5 mt-4 border-t border-[#0a1526] pt-3">
        <button 
          onClick={() => toggleSection(title.replace(/\s+/g, ''))}
          className="flex items-center gap-1.5 text-[10px] font-mono tracking-widest uppercase text-sgc-dim hover:text-sgc-bright transition-colors text-left"
        >
          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {title}
        </button>
        {isExpanded && renderJson(data)}
      </div>
    )
  }

  const additionalData = Object.fromEntries(Object.entries(payload).filter(([k]) => !['request', 'response', 'metrics', 'duration_ms', 'duration', 'latency', 'latency_ms', 'status', 'function_name', 'tool', 'action'].includes(k)))

  return (
    <div className="h-full w-full glass rounded-2xl flex flex-col relative overflow-hidden">
      
      {/* Header */}
      <div className="flex justify-between items-center p-4 border-b border-sgc-border">
        <div className="flex items-center gap-2 tp-1">
          <Activity size={16} className={colorClass} />
          <span className="text-sgc-bright">INSPECTOR</span>
          <span className="text-sgc-dim text-[10px] ml-2">{event.id}</span>
        </div>
        <button 
          onClick={onClose}
          className="text-sgc-dim hover:text-white transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 flex flex-col">
        
        {/* Title */}
        <div className="mb-4 flex flex-col gap-1">
          <div className={`text-sm font-mono tracking-wider capitalize ${colorClass}`}>
            {event.type.replace(/_/g, ' ')}
          </div>
          {!!funcName && (
            <div className="text-sgc-bright font-mono text-xs">
              {String(funcName)}()
            </div>
          )}
        </div>

        {/* Metadata Grid */}
        <div className="grid grid-cols-2 gap-4 mb-4 font-mono text-[10px] tracking-wider bg-[#050a14] p-3 rounded border border-[#0a1526]">
          <div className="flex flex-col gap-1">
            <span className="text-sgc-dim uppercase">Started</span>
            <span className="text-sgc-bright">
              {new Date(event.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })}
            </span>
          </div>
          
          <div className="flex flex-col gap-1">
            <span className="text-sgc-dim uppercase">Status</span>
            <span className={status === 'Success' ? 'text-[#00ff41]' : 'text-sgc-bright'}>
              {status === 'Success' ? '✓ ' : ''}{String(status)}
            </span>
          </div>

          {!!duration && (
            <div className="flex flex-col gap-1">
              <span className="text-sgc-dim uppercase">Duration</span>
              <span className="text-sgc-bright">{String(duration)} ms</span>
            </div>
          )}
        </div>

        {/* Event metrics */}
        {(() => {
          const m = eventMetrics(event)
          const items = [
            ['Latency', m.latency != null ? `${m.latency} ms` : null],
            ['Duration', m.duration != null ? `${m.duration} ms` : null],
            ['Confidence', m.confidence != null ? `${Math.round(m.confidence * 100)}%` : null],
            ['Tokens', m.tokens != null ? String(m.tokens) : null],
            ['Inference', m.inference],
            ['Model', m.model],
          ].filter(([, v]) => v != null) as [string, string][]
          if (items.length === 0) return null
          return (
            <div className="grid grid-cols-2 gap-4 mb-4 font-mono text-[10px] tracking-wider bg-[#050a14] p-3 rounded border border-[#0a1526]">
              {items.map(([label, value]) => (
                <div key={label} className="flex flex-col gap-1">
                  <span className="text-sgc-dim uppercase">{label}</span>
                  <span className="text-sgc-bright truncate">{value}</span>
                </div>
              ))}
            </div>
          )
        })()}

        {/* Related Events (trace) */}
        {related && related.length > 1 && (
          <div className="mb-4 flex flex-col gap-1.5 border-t border-[#0a1526] pt-3">
            <div className="flex items-center gap-1.5 text-[10px] font-mono tracking-widest uppercase text-sgc-dim mb-1">
              <GitBranch size={13} /> Related Events
            </div>
            {related.map((r, i) => {
              const rc = (EVENT_COLORS[r.type] || DEFAULT_COLOR).split(' ')[0]
              const isCurrent = r.id === event.id
              return (
                <button
                  key={r.id}
                  onClick={() => onSelectRelated?.(r)}
                  className="flex items-center gap-2 text-left group"
                >
                  <span className="flex flex-col items-center justify-center w-3">
                    <span className={`w-2 h-2 rounded-full ${rc} ${isCurrent ? 'ring-2 ring-white/40' : ''}`} />
                    {i < related.length - 1 && <span className="w-px flex-1 bg-sgc-border min-h-[10px]" />}
                  </span>
                  <span className={`text-[11px] capitalize tracking-wide ${rc} ${isCurrent ? 'font-bold' : 'opacity-80 group-hover:opacity-100'}`}>
                    {r.type.replace(/_/g, ' ')}
                  </span>
                </button>
              )
            })}
          </div>
        )}

        {/* Sections */}
        {hasRequest || hasResponse || hasMetrics ? (
          <>
            <Section title="Request" data={payload.request} />
            <Section title="Response" data={payload.response} />
            <Section title="Payload Metrics" data={payload.metrics} />
            <Section title="Additional Data" data={additionalData} />
          </>
        ) : (
          <Section title="Payload" data={payload} />
        )}
      </div>
    </div>
  )
}
