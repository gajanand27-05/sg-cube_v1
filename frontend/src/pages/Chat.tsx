import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Mic, Cpu, Volume2, Circle, Wifi, WifiOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { AssistantStatus } from '@/hooks/useWebSocket'
import { useAgentStore, useSocketStore } from '@/store'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

interface Props {
  status: AssistantStatus
}

// The state pill: one at-a-glance answer to "what is SG_CUBE doing right now?"
// Reads AssistantStatus (already wired through useWebSocket) plus the last
// active agent from agentStore to name the current tool during THINKING.
function StatePill({ status, currentTool }: { status: AssistantStatus; currentTool: string }) {
  let icon = <Circle size={12} className="fill-current" />
  let label = 'Ready'
  let color = 'text-sgc-dim border-sgc-dim'
  let pulse = false

  if (status.listening) {
    icon = <Mic size={12} />
    label = 'Listening'
    color = 'text-sgc-border-bright border-sgc-border-bright'
    pulse = true
  } else if (status.thinking) {
    icon = <Cpu size={12} />
    label = currentTool ? `Thinking · ${currentTool}` : 'Thinking'
    color = 'text-sgc-border-bright border-sgc-border-bright'
    pulse = true
  } else if (status.speaking) {
    icon = <Volume2 size={12} />
    label = 'Speaking'
    color = 'text-sgc-border-bright border-sgc-border-bright'
    pulse = true
  }

  return (
    <div className={`flex items-center gap-2 px-2.5 py-1 border font-mono text-[10px] tracking-wider ${color}`}>
      <motion.span
        animate={pulse ? { opacity: [0.4, 1, 0.4] } : { opacity: 1 }}
        transition={pulse ? { duration: 1.2, repeat: Infinity, ease: 'easeInOut' } : {}}
        className="flex items-center"
      >
        {icon}
      </motion.span>
      <span className="uppercase">{label}</span>
    </div>
  )
}

// Live view of the tools the active agent is currently running. Streams
// from agentStore's tool_call events — sidesteps the 3-blinking-dots
// black box and shows what the pipeline is actually doing.
function ThinkingTrail({ tools, reasoning }: { tools: { tool: string; latency_ms: number }[]; reasoning: string }) {
  const lastTools = tools.slice(-3)
  return (
    <div className="flex flex-col gap-1 self-start max-w-[80%]">
      <span className="font-mono text-[10px] text-sgc-dim tracking-wider">SG_CUBE</span>
      <div className="font-mono text-xs px-3.5 py-2.5 border border-sgc-border bg-[rgba(0,243,255,0.05)] text-sgc-secondary">
        {reasoning && (
          <div className="text-sgc-primary mb-1.5 leading-relaxed">{reasoning}</div>
        )}
        {lastTools.length > 0 ? (
          <div className="flex flex-col gap-0.5">
            {lastTools.map((t, i) => (
              <div key={i} className="flex items-center gap-2 text-sgc-dim">
                <span className="text-sgc-border-bright">›</span>
                <span className="text-sgc-secondary">{t.tool}</span>
                {t.latency_ms > 0 && <span className="text-sgc-dim">({t.latency_ms}ms)</span>}
              </div>
            ))}
          </div>
        ) : (
          !reasoning && (
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-sgc-primary animate-blink" />
              <span className="w-1.5 h-1.5 rounded-full bg-sgc-primary animate-blink" style={{ animationDelay: '0.2s' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-sgc-primary animate-blink" style={{ animationDelay: '0.4s' }} />
            </div>
          )
        )}
      </div>
    </div>
  )
}

export function Chat({ status }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Live agent activity — no polling, no fetches, comes from the WS bus.
  const agents = useAgentStore((s) => s.agents)
  const activeAgent = useAgentStore((s) => s.activeAgent)
  const connected = useSocketStore((s) => s.connected)

  const active = agents.find((a) => a.name === activeAgent)
  const currentTool = active?.tools[active.tools.length - 1]?.tool ?? ''
  const showTrail = (status.thinking || loading) && (active?.tools.length || active?.reasoning)

  useEffect(() => {
    if (status.lastResponse && !loading) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: status.lastResponse, timestamp: Date.now() },
      ])
    }
  }, [status.lastResponse])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, status.thinking, active?.tools.length])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setLoading(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text, timestamp: Date.now() },
    ])
    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ text }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.response || 'Done', timestamp: Date.now() },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Error processing request', timestamp: Date.now() },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-baseline gap-3">
          <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Chat</h1>
          <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Talk to SG_CUBE</span>
        </div>
        <div
          className={`flex items-center gap-1.5 font-mono text-[10px] tracking-wider ${
            connected ? 'text-sgc-border-bright' : 'text-sgc-danger'
          }`}
          title={connected ? 'WebSocket connected' : 'WebSocket disconnected — retrying every 3s'}
        >
          {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
          <span className="uppercase">{connected ? 'live' : 'offline'}</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-3 py-2">
        {messages.length === 0 && !showTrail && !loading && (
          <div className="flex-1 flex flex-col items-center justify-center gap-2">
            <div className="font-sans text-2xl font-bold text-sgc-bright tracking-[2px]">Hello, Gajanand</div>
            <div className="font-sans text-lg text-sgc-secondary">How can I help today?</div>
          </div>
        )}
        <AnimatePresence>
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex flex-col gap-1 max-w-[80%] ${msg.role === 'user' ? 'self-end items-end' : 'self-start items-start'}`}
            >
              <span className="font-mono text-[10px] text-sgc-dim tracking-wider">
                {msg.role === 'user' ? 'You' : 'SG_CUBE'}
              </span>
              <div className={`font-mono text-sm leading-relaxed px-3.5 py-2.5 border ${
                msg.role === 'user'
                  ? 'bg-[rgba(0,243,255,0.1)] border-sgc-dim text-sgc-bright'
                  : 'bg-[rgba(0,243,255,0.05)] border-sgc-border text-sgc-primary'
              }`}>
                {msg.content}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {(showTrail || loading) && (
          <ThinkingTrail tools={active?.tools ?? []} reasoning={active?.reasoning ?? ''} />
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex flex-col gap-2 pt-3 border-t border-sgc-border shrink-0">
        <div className="flex items-center gap-2">
          <StatePill status={status} currentTool={currentTool} />
          {status.confidence < 100 && status.confidence > 0 && (
            <span className="font-mono text-[10px] text-sgc-dim tracking-wider">
              confidence · {Math.round(status.confidence)}%
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <input
            className="flex-1 bg-[rgba(0,243,255,0.05)] border border-sgc-border text-sgc-primary font-mono text-sm px-3.5 py-2.5 outline-none focus:border-sgc-border-bright"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="Type a message..."
            disabled={loading}
          />
          <Button size="icon" onClick={send} disabled={loading || !input.trim()}>
            <Send size={16} />
          </Button>
        </div>
      </div>
    </div>
  )
}
