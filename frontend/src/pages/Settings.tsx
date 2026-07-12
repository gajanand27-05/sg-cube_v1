import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { THEMES, applyTheme, getStoredTheme, type ThemeName } from '@/lib/theme'

export function Settings() {
  const [email, setEmail] = useState('Not logged in')
  const [theme, setTheme] = useState<ThemeName>(getStoredTheme())

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

  const chooseTheme = (id: ThemeName) => {
    setTheme(id)
    applyTheme(id)
  }

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

        {/* Theme switcher — flips the [data-theme] CSS block app-wide */}
        <div className="flex items-center py-3 border-b border-[rgba(0,243,255,0.08)]">
          <span className="font-mono text-[11px] text-sgc-dim tracking-wider w-40 shrink-0">Theme</span>
          <div className="flex gap-2">
            {THEMES.map((t) => (
              <button
                key={t.id}
                onClick={() => chooseTheme(t.id)}
                className={cn(
                  "flex items-center gap-2 px-3 py-1 border font-mono text-[11px] tracking-wider transition-colors",
                  theme === t.id
                    ? "border-sgc-border-bright text-sgc-border-bright"
                    : "border-sgc-border text-sgc-dim hover:text-sgc-secondary"
                )}
              >
                <span
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ background: t.swatch, boxShadow: `0 0 6px ${t.swatch}` }}
                />
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

