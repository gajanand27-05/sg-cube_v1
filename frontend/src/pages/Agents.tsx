import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronUp, Cpu, Clock, CheckCircle, XCircle, AlertTriangle, Brain, Wrench, Radio } from 'lucide-react'
import { useAgentStore, useSocketStore } from '@/store'

const STATUS_COLORS: Record<string, string> = {
  thinking: 'text-sgc-border-bright border-sgc-border-bright shadow-[0_0_10px_rgba(0,229,255,0.25)]',
  completed: 'text-[#00ff41] border-[#00ff41] shadow-[0_0_10px_rgba(0,255,65,0.2)]',
  verified: 'text-[#00ff41] border-[#00ff41] shadow-[0_0_10px_rgba(0,255,65,0.2)]',
  failed: 'text-sgc-danger border-sgc-danger shadow-[0_0_10px_rgba(255,0,60,0.2)]',
  standby: 'text-sgc-dim border-sgc-border',
}

const STATUS_BADGES: Record<string, string> = {
  thinking: 'THINKING',
  completed: 'COMPLETED',
  verified: 'VERIFIED',
  failed: 'FAILED',
  standby: 'STANDBY',
}

// Truncate + tail-only for the inline preview under the agent name.
// Show the last ~90 chars — enough for a sentence, doesn't push the row.
function tailPreview(text: string, chars = 90): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length <= chars ? clean : '…' + clean.slice(-chars)
}

export function Agents() {
  const { agents, activeAgent, setAgents } = useAgentStore()
  const connected = useSocketStore((s) => s.connected)
  const [expanded, setExpanded] = useState<string | null>(null)

  // Initial fetch once — after that, WS drives the store. Previously this
  // polled every 5s, which would overwrite in-progress streamed reasoning
  // if a poll landed mid-turn. WS updates are incremental, so a running
  // poll on top is worse than useless.
  useEffect(() => {
    let alive = true
    fetch('/agents/status', { credentials: 'include' })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d && alive) setAgents(d.agents || [], d.active_agent || null) })
      .catch(() => {/* offline */})
    return () => { alive = false }
  }, [setAgents])

  const knownAgents = ['Commander', 'Planner', 'Guardian', 'Operator', 'Watcher']
  const merged = useMemo(() => knownAgents.map((name) => {
    const found = agents.find((a) => a.name === name)
    return found ?? {
      name, status: 'standby', is_thinking: false, current_action: null,
      reasoning: '', tools: [], confidence: 100, latency_ms: 0,
      summary: null, last_seen: '', details: {},
    }
  }), [agents])

  // Which agent is streaming right now? Used for the global "current turn"
  // banner and to auto-open the corresponding card during thought.
  const streaming = merged.find((a) => a.is_thinking)

  const toggle = (name: string) => setExpanded(expanded === name ? null : name)

  return (
    <div className="h-full flex flex-col p-4 overflow-hidden">
      <div className="flex items-baseline gap-3 mb-3 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Agents</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Agent Inspector</span>
        <span className={`ml-auto flex items-center gap-1.5 font-mono text-[10px] tracking-wider ${connected ? 'text-sgc-border-bright' : 'text-sgc-dim'}`}>
          {connected ? <Radio size={11} /> : <span className="w-2 h-2 rounded-full bg-sgc-dim" />}
          {connected ? 'LIVE' : 'OFFLINE'}
        </span>
      </div>

      {/* Global "current turn" banner — appears only when an agent is streaming */}
      <AnimatePresence>
        {streaming && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-3 border border-sgc-border-bright bg-[rgba(0,229,255,0.05)] px-3 py-2 flex items-center gap-3 overflow-hidden"
          >
            <motion.div
              className="w-2 h-2 rounded-full bg-sgc-border-bright shadow-[0_0_8px_#00e5ff] shrink-0"
              animate={{ opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
            />
            <span className="font-mono text-[10px] text-sgc-dim tracking-wider uppercase shrink-0">Live · {streaming.name}</span>
            <div className="font-mono text-[11px] text-sgc-secondary flex-1 truncate">
              {streaming.current_action || tailPreview(streaming.reasoning) || 'starting…'}
            </div>
            {streaming.tools.length > 0 && (
              <span className="font-mono text-[10px] text-sgc-border-bright shrink-0">
                {streaming.tools.length} tool{streaming.tools.length === 1 ? '' : 's'}
              </span>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex-1 overflow-y-auto space-y-2">
        {merged.map((agent, i) => {
          const isActive = agent.name === activeAgent || agent.is_thinking
          const colorClass = STATUS_COLORS[agent.status] || STATUS_COLORS.standby
          const badge = STATUS_BADGES[agent.status] || agent.status.toUpperCase()
          // Auto-open the currently thinking card. User's manual expand still
          // takes precedence for other cards.
          const isOpen = expanded === agent.name || agent.is_thinking
          const hasReasoning = agent.reasoning && agent.reasoning.length > 0

          return (
            <motion.div
              key={agent.name}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="border bg-[rgba(0,243,255,0.02)] transition-colors"
              style={{ borderColor: isActive ? 'var(--sgc-border-bright)' : 'var(--sgc-border)' }}
            >
              <button
                className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-[rgba(0,243,255,0.04)] transition-colors cursor-pointer"
                onClick={() => toggle(agent.name)}
              >
                {/* Status dot — pulses when thinking */}
                <motion.span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{
                    background: agent.is_thinking ? '#00e5ff'
                      : agent.status === 'failed' ? '#ff0033'
                      : agent.status === 'completed' || agent.status === 'verified' ? '#00ff41'
                      : '#005577',
                    boxShadow: agent.is_thinking ? '0 0 10px #00e5ff'
                      : agent.status === 'completed' || agent.status === 'verified' ? '0 0 8px #00ff41'
                      : agent.status === 'failed' ? '0 0 8px #ff0033'
                      : 'none',
                  }}
                  animate={agent.is_thinking ? { opacity: [0.4, 1, 0.4] } : { opacity: 1 }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
                />

                {/* Name + action + streaming reasoning tail */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <div className="font-sans font-bold text-sm tracking-wider text-sgc-bright">{agent.name}</div>
                    {agent.current_action && (
                      <div className="font-mono text-[10px] text-sgc-dim truncate">{agent.current_action}</div>
                    )}
                  </div>
                  {/* When collapsed and thinking, show a preview so the user can
                      watch progress without expanding. */}
                  {!isOpen && agent.is_thinking && hasReasoning && (
                    <div className="font-mono text-[10px] text-sgc-secondary truncate mt-0.5">
                      {tailPreview(agent.reasoning, 70)}
                      <span className="text-sgc-border-bright animate-blink">▎</span>
                    </div>
                  )}
                </div>

                <span className={`font-mono text-[10px] tracking-wider px-2.5 py-0.5 border shrink-0 ${colorClass}`}>
                  {badge}
                </span>

                <span className="font-mono text-xs text-sgc-dim w-12 text-right shrink-0">
                  {agent.confidence.toFixed(0)}%
                </span>

                <span className="text-sgc-dim shrink-0">
                  {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </span>
              </button>

              <AnimatePresence>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="px-4 pb-4 pt-1 border-t border-sgc-border space-y-3">
                      {/* Streaming reasoning with cursor while thinking */}
                      {hasReasoning && (
                        <DetailSection icon={Brain} label="Reasoning" trailing={
                          agent.is_thinking && (
                            <span className="ml-2 font-mono text-[9px] tracking-wider text-sgc-border-bright uppercase animate-blink">
                              streaming
                            </span>
                          )
                        }>
                          <StreamingReasoning text={agent.reasoning} thinking={agent.is_thinking} />
                        </DetailSection>
                      )}

                      {agent.tools.length > 0 && (
                        <DetailSection icon={Wrench} label={`Tools (${agent.tools.length})`}>
                          <ToolList tools={agent.tools} />
                        </DetailSection>
                      )}

                      {/* Metrics row */}
                      <div className="flex flex-wrap gap-6">
                        <div className="flex items-center gap-1.5">
                          <Clock size={12} className="text-sgc-dim" />
                          <span className="font-mono text-[11px] text-sgc-dim">Latency</span>
                          <span className="font-mono text-xs text-sgc-bright">
                            {agent.latency_ms > 0 ? `${agent.latency_ms}ms` : '—'}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Cpu size={12} className="text-sgc-dim" />
                          <span className="font-mono text-[11px] text-sgc-dim">Confidence</span>
                          <span className={`font-mono text-xs ${agent.confidence > 80 ? 'text-[#00ff41]' : 'text-sgc-warn'}`}>
                            {agent.confidence.toFixed(0)}%
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          {agent.status === 'completed' || agent.status === 'verified' ? (
                            <CheckCircle size={12} className="text-[#00ff41]" />
                          ) : agent.status === 'failed' ? (
                            <XCircle size={12} className="text-sgc-danger" />
                          ) : (
                            <AlertTriangle size={12} className="text-sgc-dim" />
                          )}
                          <span className="font-mono text-[11px] text-sgc-dim">Status</span>
                          <span className="font-mono text-xs text-sgc-bright">
                            {agent.summary || agent.status}
                          </span>
                        </div>
                      </div>

                      {agent.last_seen && (
                        <div className="font-mono text-[10px] text-sgc-dim">
                          Last seen: {new Date(agent.last_seen).toLocaleString()}
                        </div>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}

// Reasoning renderer with tail auto-scroll and a blinking cursor while
// the underlying agent is still streaming tokens.
function StreamingReasoning({ text, thinking }: { text: string; thinking: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Keep the newest tokens in view during streaming.
    if (thinking && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight
    }
  }, [text, thinking])
  return (
    <div ref={ref} className="max-h-56 overflow-y-auto font-mono text-xs text-sgc-secondary leading-relaxed whitespace-pre-wrap pr-2">
      {text}
      {thinking && <span className="text-sgc-border-bright animate-blink">▎</span>}
    </div>
  )
}

// Full tool history, most recent first. No 5-item truncation — a real
// agent run can hit 20+ tool calls and the whole trace matters for audit.
function ToolList({ tools }: { tools: { tool: string; args: unknown; result: string; latency_ms: number; timestamp: string }[] }) {
  return (
    <div className="max-h-72 overflow-y-auto space-y-1 pr-2">
      {[...tools].reverse().map((t, j) => (
        <div key={j} className="font-mono text-[11px] flex items-start gap-2 border-b border-sgc-border pb-1 last:border-0">
          <span className="text-sgc-primary shrink-0 w-32 truncate">{t.tool}</span>
          <span className="text-sgc-dim text-[10px] shrink-0 w-12 text-right">
            {t.latency_ms > 0 ? `${t.latency_ms}ms` : ''}
          </span>
          <span className="text-sgc-secondary truncate flex-1">
            {t.result || t.args ? JSON.stringify(t.args || t.result).slice(0, 100) : ''}
          </span>
        </div>
      ))}
    </div>
  )
}

function DetailSection({ icon: Icon, label, children, trailing }: {
  icon: React.ElementType; label: string; children: React.ReactNode; trailing?: React.ReactNode
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon size={12} className="text-sgc-primary" />
        <span className="font-mono text-[10px] text-sgc-dim tracking-wider">{label}</span>
        {trailing}
      </div>
      {children}
    </div>
  )
}
