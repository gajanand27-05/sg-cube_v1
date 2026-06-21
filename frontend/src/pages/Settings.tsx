import { useState, useEffect } from 'react'

export function Settings() {
  const [email, setEmail] = useState('Not logged in')

  useEffect(() => {
    fetch('/auth/whoami', { credentials: 'include' })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) setEmail(data.email || data.id || 'Unknown')
      })
      .catch(() => {})
  }, [])

  const settings = [
    { label: 'User', value: email },
    { label: 'Wake Phrase', value: 'onyx' },
    { label: 'STT Model', value: 'faster-whisper (small)' },
    { label: 'LLM Model', value: 'Ollama (phi3 / gemma4:12b)' },
  ]

  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Settings</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Configuration</span>
      </div>
      <div className="space-y-0">
        {settings.map((s, i) => (
          <div key={i} className="flex items-center py-3 border-b border-[rgba(0,243,255,0.08)]">
            <span className="font-mono text-[11px] text-sgc-dim tracking-wider w-40 shrink-0">{s.label}</span>
            <span className="font-mono text-sm text-sgc-bright">{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
