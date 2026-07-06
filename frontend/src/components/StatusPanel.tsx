import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { AssistantStatus, SystemStats, WsEvent } from '@/hooks/useWebSocket'

interface Props {
  status: AssistantStatus
  systemStats: SystemStats
  events?: WsEvent[]
}

// Assistant-state colour map so the top header reads at a glance.
const STATE_COLORS: Record<string, string> = {
  IDLE:      'text-sgc-secondary',
  LISTENING: 'text-sgc-warn',
  THINKING:  'text-sgc-border-bright',
  SPEAKING:  'text-[#00ff41]',
}

// Event severity — used to colour the live ticker. Any event type not
// listed here falls back to "info". Failure/error events read as danger,
// completion/verify as success, routine ticks are dim, everything else
// is standard cyan info.
type Severity = 'success' | 'danger' | 'info' | 'muted'

function eventSeverity(e: WsEvent): Severity {
  const t = e.type
  const p = e.payload as Record<string, unknown> | undefined
  const statusField = (p?.status as string | undefined)?.toLowerCase()
  if (statusField === 'failed' || statusField === 'error') return 'danger'
  if (t === 'agent_completed' && statusField === 'completed') return 'success'
  if (t === 'agent_completed' && statusField === 'verified') return 'success'
  if (t === 'tool_finished') return 'success'
  if (t === 'spoken_response') return 'success'
  if (t === 'system_stats' || t === 'confidence_event') return 'muted'
  return 'info'
}

const SEVERITY_COLORS: Record<Severity, { dot: string; text: string; label: string }> = {
  success: { dot: '#00ff41', text: 'text-[#00ff41]',        label: 'text-sgc-secondary' },
  danger:  { dot: '#ff0033', text: 'text-sgc-danger',       label: 'text-sgc-danger' },
  info:    { dot: '#00e5ff', text: 'text-sgc-border-bright', label: 'text-sgc-secondary' },
  muted:   { dot: '#005577', text: 'text-sgc-dim',           label: 'text-sgc-dim' },
}

// Human-friendly one-liner extracted from the event payload. Keeps the
// ticker readable without needing to expand.
function eventSummary(e: WsEvent): string {
  const p = e.payload as Record<string, unknown> | undefined
  if (!p) return ''
  const s = (k: string) => (typeof p[k] === 'string' ? (p[k] as string) : undefined)
  return s('text') || s('action') || s('agent_name') || s('tool_name') || s('tool') || s('reasoning') || s('summary') || s('query') || ''
}

function eventLabel(type: string): string {
  return type.replace(/_/g, ' ')
}

function formatBps(bps: number): string {
  if (bps < 1024) return `${bps.toFixed(0)} B/s`
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`
  return `${(bps / 1024 / 1024).toFixed(1)} MB/s`
}

// The ticker uses "muted" for system_stats/confidence noise but they
// still overwhelm signal. Filter them out entirely.
const HIDDEN_TYPES = new Set(['system_stats', 'confidence_event'])

export function StatusPanel({ status, systemStats, events = [] }: Props) {
  const {
    cpu_percent = 0,
    memory_percent = 0,
    memory_used_gb = 0,
    memory_total_gb = 0,
    disk_percent = 0,
    disk_used_gb = 0,
    disk_total_gb = 0,
    net_down_bps = 0,
    net_up_bps = 0,
  } = systemStats || {}

  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  const visibleEvents = events.filter((e) => !HIDDEN_TYPES.has(e.type))
  const recent = visibleEvents.slice(-10).reverse()

  return (
    <aside className="w-[260px] border-l border-sgc-border-bright flex flex-col overflow-y-auto bg-[rgba(0,229,255,0.02)]">

      {/* Assistant Status */}
      <div className="border-b border-sgc-border p-3">
        <h3 className="h-caption mb-3">Assistant Status</h3>
        <div className="space-y-2">
          <Row label="STATE" value={
            <motion.span
              key={status.state}
              className={`font-mono text-sm ${STATE_COLORS[status.state] || 'text-sgc-secondary'}`}
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
            >
              {status.state || 'IDLE'}
            </motion.span>
          } />
          <Row label="AGENT" value={status.currentAgent || '—'} />
          <Row label="CONFIDENCE" value={`${status.confidence?.toFixed(0) || '—'}%`} />
          <Row label="TOOL" value={status.lastTool || '—'} />
        </div>
      </div>

      {/* System Monitor */}
      <div className="border-b border-sgc-border p-3">
        <h3 className="h-caption mb-3">System Monitor</h3>
        <div className="space-y-3">
          <Meter label="CPU"    value={cpu_percent} />
          <Meter label="MEMORY" value={memory_percent} sub={`${memory_used_gb.toFixed(1)} / ${memory_total_gb.toFixed(1)} GiB`} />
          <Meter label="DISK"   value={disk_percent}   sub={`${disk_used_gb.toFixed(0)} / ${disk_total_gb.toFixed(0)} GiB`} />
          <div className="flex justify-between items-center">
            <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">NETWORK</span>
            <span className="font-mono text-[10px] text-sgc-bright">
              <span className="text-sgc-secondary">↓</span> {formatBps(net_down_bps)} <span className="text-sgc-secondary">↑</span> {formatBps(net_up_bps)}
            </span>
          </div>
        </div>
      </div>

      {/* Live Events — severity-coloured, timestamps, click to expand */}
      <div className="p-3 flex-1 min-h-0 flex flex-col">
        <div className="flex items-center justify-between mb-2 shrink-0">
          <h3 className="h-caption">Live Events</h3>
          <span className="font-mono text-[9px] text-sgc-dim">
            {visibleEvents.length} · {events.length - visibleEvents.length} muted
          </span>
        </div>
        <div className="flex-1 overflow-y-auto space-y-1 pr-1 min-h-0">
          <AnimatePresence initial={false}>
            {recent.length === 0 && (
              <div className="text-sgc-dim font-mono text-[10px] italic">Waiting for events…</div>
            )}
            {recent.map((e, i) => {
              const sev = eventSeverity(e)
              const col = SEVERITY_COLORS[sev]
              const summary = eventSummary(e)
              const isOpen = expandedIdx === i
              const ts = new Date(e.timestamp).toLocaleTimeString('en-US', { hour12: false })
              return (
                <motion.div
                  key={`${e.timestamp}-${i}`}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0 }}
                  className="border border-sgc-border/60 bg-[rgba(0,229,255,0.02)]"
                >
                  <button
                    className="w-full text-left px-2 py-1.5 flex items-start gap-1.5 hover:bg-[rgba(0,229,255,0.05)] transition-colors cursor-pointer"
                    onClick={() => setExpandedIdx(isOpen ? null : i)}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full mt-1 shrink-0"
                      style={{ background: col.dot, boxShadow: sev !== 'muted' ? `0 0 4px ${col.dot}` : 'none' }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline justify-between gap-1">
                        <span className={`font-mono text-[10px] tracking-wider uppercase truncate ${col.text}`}>
                          {eventLabel(e.type)}
                        </span>
                        <span className="font-mono text-[9px] text-sgc-dim tabular-nums shrink-0">{ts}</span>
                      </div>
                      {summary && !isOpen && (
                        <div className={`font-mono text-[10px] truncate mt-0.5 ${col.label}`}>
                          {summary}
                        </div>
                      )}
                    </div>
                  </button>
                  <AnimatePresence>
                    {isOpen && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden"
                      >
                        <div className="px-2 pb-2 pt-1 border-t border-sgc-border/60">
                          <pre className="font-mono text-[9px] text-sgc-secondary whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
                            {JSON.stringify(e.payload ?? {}, null, 2)}
                          </pre>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
      </div>
    </aside>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center">
      <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">{label}</span>
      {typeof value === 'string' ? (
        <span className="font-mono text-sm text-sgc-bright truncate max-w-[60%] text-right">{value}</span>
      ) : value}
    </div>
  )
}

function Meter({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">{label}</span>
        <span className="font-mono text-[10px] text-sgc-bright tabular-nums">{value.toFixed(1)}%</span>
      </div>
      {sub && <div className="font-mono text-[9px] text-sgc-dim mb-1 tabular-nums">{sub}</div>}
      <div className="h-1.5 bg-sgc-border rounded-full overflow-hidden">
        <motion.div
          className={value > 85 ? 'h-full bg-sgc-danger rounded-full' : 'h-full bg-sgc-border-bright rounded-full shadow-[0_0_4px_#00f3ff]'}
          initial={{ width: 0 }}
          animate={{ width: `${Math.max(0, Math.min(100, value))}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
    </div>
  )
}
