import { useState, useRef, useEffect } from 'react'
import type { AssistantStatus } from '../hooks/useWebSocket'

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
      const reply = data.response || 'Done'
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: reply, timestamp: Date.now() },
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
    <div className="page chat-page">
      <div className="page-header">
        <h1>Chat</h1>
        <span className="page-subtitle">Talk to SG_CUBE</span>
      </div>
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-greeting">Hello, Gajanand</div>
            <div className="chat-prompt">How can I help today?</div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-msg chat-msg-${msg.role}`}>
            <div className="chat-msg-label">{msg.role === 'user' ? 'You' : 'SG_CUBE'}</div>
            <div className="chat-msg-content">{msg.content}</div>
          </div>
        ))}
        {loading && (
          <div className="chat-msg chat-msg-assistant">
            <div className="chat-msg-label">SG_CUBE</div>
            <div className="chat-typing">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="chat-input-bar">
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="Type a message..."
          disabled={loading}
        />
        <button className="chat-send" onClick={send} disabled={loading || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  )
}
