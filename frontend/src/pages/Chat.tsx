import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { AssistantStatus } from '@/hooks/useWebSocket'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

interface Props {
  status: AssistantStatus
}

export function Chat({ status }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

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
  }, [messages])

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
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Chat</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Talk to SG_CUBE</span>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-3 py-2">
        {messages.length === 0 && (
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
        {loading && (
          <div className="flex flex-col gap-1 self-start">
            <span className="font-mono text-[10px] text-sgc-dim">SG_CUBE</span>
            <div className="flex gap-1 px-3.5 py-2.5">
              <span className="w-2 h-2 rounded-full bg-sgc-primary animate-blink" />
              <span className="w-2 h-2 rounded-full bg-sgc-primary animate-blink" style={{ animationDelay: '0.2s' }} />
              <span className="w-2 h-2 rounded-full bg-sgc-primary animate-blink" style={{ animationDelay: '0.4s' }} />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2 pt-3 border-t border-sgc-border shrink-0">
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
  )
}
