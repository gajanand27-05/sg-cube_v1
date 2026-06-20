import { useState, useEffect } from 'react'

export function Settings() {
  const [settings, setSettings] = useState<Record<string, string>>({})

  useEffect(() => {
    fetch('/auth/whoami', { credentials: 'include' })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) setSettings({ email: data.email || data.id || 'Unknown' })
      })
      .catch(() => {})
  }, [])

  return (
    <div className="page">
      <div className="page-header">
        <h1>Settings</h1>
        <span className="page-subtitle">Configuration</span>
      </div>
      <div className="settings-section">
        <div className="settings-label">User</div>
        <div className="settings-value">{settings.email || 'Not logged in'}</div>
      </div>
      <div className="settings-section">
        <div className="settings-label">Wake Phrase</div>
        <div className="settings-value">onyx</div>
      </div>
      <div className="settings-section">
        <div className="settings-label">STT Model</div>
        <div className="settings-value">faster-whisper (small)</div>
      </div>
      <div className="settings-section">
        <div className="settings-label">LLM Model</div>
        <div className="settings-value">Ollama (phi3 / gemma4:12b)</div>
      </div>
    </div>
  )
}
