import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronUp, Cpu, Clock, CheckCircle, XCircle, AlertTriangle, Brain, Wrench } from 'lucide-react'
import { useAgentStore, useSocketStore } from '@/store'

const STATUS_COLORS: Record<string, string> = {
  thinking: 'text-[#00ff41] border-[#00ff41] shadow-[0_0_10px_rgba(0,255,65,0.2)]',
  completed: 'text-sgc-primary border-sgc-border-bright shadow-[0_0_10px_rgba(0,243,255,0.2)]',
  verified: 'text-[#00ff41] border-[#00ff41] shadow-[0_0_10px_rgba(0,255,65,0.15)]',
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

export function Agents() {
  const { agents, activeAgent, setAgents } = useAgentStore()
  const connected = useSocketStore((s) => s.connected)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchStatus = async () => {
    setLoading(true)
    try {
      const res = await fetch('/agents/status', { credentials: 'include' })
      const data = await res.json()
      setAgents(data.agents || [], data.active_agent || null)
    } catch {
      /* offline */
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 5000)
    return () => clearInterval(interval)
  }, [])

  const knownAgents = ['Commander', 'Planner', 'Guardian', 'Operator', 'Watcher']
  const merged = knownAgents.map((name) => {
    const found = agents.find((a) => a.name === name)
    return found ?? {
      name,
      status: 'standby',
      is_thinking: false,
      current_action: null,
      reasoning: '',
      tools: [],
      confidence: 100,
      latency_ms: 0,
      summary: null,
      last_seen: '',
      details: {},
    }
  })

  const toggle = (name: string) => setExpanded(expanded === name ? null : name)

  return (
    <div className="h-full flex flex-col p-4 overflow-hidden">
      <div className="flex items-baseline gap-3 mb-3 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Agents</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Agent Inspector</span>
        <span className={`ml-auto font-mono text-[10px] ${connected ? 'text-[#00ff41]' : 'text-sgc-dim'}`}>
          {connected ? '● LIVE' : '○ OFFLINE'}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2">
        <AnimatePresence>
          {merged.map((agent, i) => {
            const isActive = agent.name === activeAgent
            const colorClass = STATUS_COLORS[agent.status] || STATUS_COLORS.standby
            const badge = STATUS_BADGES[agent.status] || agent.status.toUpperCase()
            const isOpen = expanded === agent.name

            return (
              <motion.div
                key={agent.name}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className="border bg-[rgba(0,243,255,0.02)]"
                style={{ borderColor: isActive ? 'var(--sgc-border-bright)' : 'var(--sgc-border)' }}
              >
                {/* Header — clickable */}
                <button
                  className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-[rgba(0,243,255,0.04)] transition-colors cursor-pointer"
                  onClick={() => toggle(agent.name)}
                >
                  {/* Status dot */}
                  <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${isActive ? 'bg-[#00ff41] shadow-[0_0_8px_#00ff41]' : 'bg-sgc-dim'}`} />

                  {/* Name + action */}
                  <div className="flex-1 min-w-0">
                    <div className="font-sans font-bold text-sm tracking-wider text-sgc-bright">{agent.name}</div>
                    {agent.current_action && (
                      <div className="font-mono text-[10px] text-sgc-dim truncate mt-0.5">{agent.current_action}</div>
                    )}
                  </div>

                  {/* Badge */}
                  <span className={`font-mono text-[10px] tracking-wider px-2.5 py-0.5 border shrink-0 ${colorClass}`}>
                    {badge}
                  </span>

                  {/* Confidence */}
                  <span className="font-mono text-xs text-sgc-dim w-12 text-right shrink-0">
                    {agent.confidence.toFixed(0)}%
                  </span>

                  {/* Chevron */}
                  <span className="text-sgc-dim shrink-0">
                    {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </span>
                </button>

                {/* Expanded details */}
                <AnimatePresence>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="px-4 pb-4 pt-1 border-t border-sgc-border space-y-3">
                        {/* Reasoning */}
                        {agent.reasoning && (
                          <DetailSection icon={Brain} label="Reasoning">
                            <div className="font-mono text-xs text-sgc-secondary leading-relaxed whitespace-pre-wrap">
                              {agent.reasoning}
                            </div>
                          </DetailSection>
                        )}

                        {/* Tools Called */}
                        {agent.tools.length > 0 && (
                          <DetailSection icon={Wrench} label={`Tools Called (${agent.tools.length})`}>
                            <div className="space-y-1">
                              {agent.tools.slice(-5).reverse().map((t, j) => (
                                <div key={j} className="font-mono text-[11px] flex items-start gap-2 border-b border-sgc-border pb-1 last:border-0">
                                  <span className="text-sgc-primary shrink-0">{t.tool}</span>
                                  <span className="text-sgc-dim text-[10px]">
                                    {t.latency_ms > 0 ? `${t.latency_ms}ms` : ''}
                                  </span>
                                  <span className="text-sgc-secondary truncate flex-1">
                                    {t.result || t.args ? JSON.stringify(t.args || t.result).slice(0, 80) : ''}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </DetailSection>
                        )}

                        {/* Metrics row */}
                        <div className="flex gap-6">
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
                            {agent.status === 'completed' ? (
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

                        {/* Last seen */}
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
        </AnimatePresence>

        {merged.length === 0 && !loading && (
          <div className="flex items-center justify-center h-32 font-mono text-sm text-sgc-dim">
            Waiting for agent data...
          </div>
        )}
      </div>
    </div>
  )
}

function DetailSection({ icon: Icon, label, children }: { icon: React.ElementType; label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon size={12} className="text-sgc-primary" />
        <span className="font-mono text-[10px] text-sgc-dim tracking-wider">{label}</span>
      </div>
      {children}
    </div>
  )
}
