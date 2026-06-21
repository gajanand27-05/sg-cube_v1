import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { RefreshCw, Search, Monitor, Eye, FileText, Clock, Image } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

interface Observation {
  content: string
  app: string
  keywords: string
  created_at: string
}

interface VisualMemory {
  content: string
  app: string
  timestamp: string
}

export function Vision() {
  const [screenshot, setScreenshot] = useState<string | null>(null)
  const [activeWindow, setActiveWindow] = useState('')
  const [windows, setWindows] = useState<string[]>([])
  const [observations, setObservations] = useState<Observation[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<VisualMemory[]>([])
  const [searching, setSearching] = useState(false)
  const [lastUpdate, setLastUpdate] = useState('')
  const [tab, setTab] = useState<'screenshot' | 'observations' | 'memory'>('screenshot')

  const refresh = async () => {
    const [ssRes, winRes, obsRes] = await Promise.all([
      fetch('/vision/screenshot', { credentials: 'include' }).catch(() => null),
      fetch('/vision/windows', { credentials: 'include' }).then(r => r.json()).catch(() => ({})),
      fetch('/vision/observations?limit=20', { credentials: 'include' }).then(r => r.json()).catch(() => ({})),
    ])
    if (ssRes?.ok) {
      setScreenshot(URL.createObjectURL(await ssRes.blob()))
    }
    setWindows((winRes as any).windows || [])
    setActiveWindow((winRes as any).active || '')
    setObservations((obsRes as any).observations || [])
    setLastUpdate(new Date().toLocaleTimeString())
  }

  useEffect(() => { refresh() }, [])

  const searchMemory = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    setTab('memory')
    try {
      const res = await fetch(`/vision/memory/search?q=${encodeURIComponent(searchQuery)}&limit=10`, {
        credentials: 'include',
      })
      const data = await res.json()
      setSearchResults(data.results || [])
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="h-full flex flex-col p-4 overflow-hidden">
      {/* Header */}
      <div className="flex items-baseline gap-3 mb-3 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Vision</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Screen Awareness Dashboard</span>
        <Button variant="ghost" size="sm" onClick={refresh} className="ml-auto">
          <RefreshCw size={14} className="mr-1" /> Refresh
        </Button>
      </div>

      {/* Active window bar */}
      <div className="flex items-center gap-2 mb-3 font-mono text-xs text-sgc-secondary shrink-0 border border-sgc-border px-3 py-1.5 bg-[rgba(0,243,255,0.03)]">
        <Monitor size={14} className="text-sgc-primary" />
        <span className="text-sgc-dim">Active Window:</span>
        <span className="text-sgc-bright">{activeWindow || 'Unknown'}</span>
        {lastUpdate && <span className="ml-auto text-sgc-dim">Last refresh: {lastUpdate}</span>}
      </div>

      {/* Tab bar */}
      <div className="flex gap-0 mb-3 border-b border-sgc-border shrink-0">
        {([
          { id: 'screenshot', label: 'Screen', icon: Image },
          { id: 'observations', label: 'Observations', icon: Clock },
          { id: 'memory', label: 'Visual Memory', icon: FileText },
        ] as const).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`flex items-center gap-1.5 font-sans text-sm font-semibold tracking-wider px-4 py-2 border-b-2 bg-transparent ${
              tab === id ? 'text-sgc-border-bright border-sgc-border-bright' : 'text-sgc-dim border-transparent hover:text-sgc-secondary'
            }`}
            onClick={() => setTab(id)}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === 'screenshot' && (
          <div className="h-full flex gap-4">
            {/* Screenshot */}
            <div className="flex-1 flex flex-col items-center justify-center gap-3 min-h-0">
              <AnimatePresence mode="wait">
                {screenshot ? (
                  <motion.img
                    key={screenshot}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    src={screenshot}
                    alt="Current screen"
                    className="max-w-full max-h-full border border-sgc-border shadow-[0_0_20px_rgba(0,243,255,0.1)] object-contain"
                  />
                ) : (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex flex-col items-center gap-2 text-sgc-dim"
                  >
                    <Eye size={40} />
                    <span className="font-mono text-sm">No screenshot available</span>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            {/* Open windows list */}
            <div className="w-72 shrink-0 overflow-y-auto">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Monitor size={14} />
                    Open Windows ({windows.length})
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-1 font-mono text-[11px]">
                    {windows.map((w, i) => (
                      <div
                        key={i}
                        className={`px-2 py-1 truncate rounded ${
                          w === activeWindow ? 'bg-[rgba(0,243,255,0.1)] text-sgc-primary' : 'text-sgc-dim hover:text-sgc-secondary'
                        }`}
                      >
                        {w === activeWindow && <span className="text-sgc-primary mr-1">▸</span>}
                        {w}
                      </div>
                    ))}
                    {windows.length === 0 && <div className="text-sgc-dim">No windows detected</div>}
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        )}

        {tab === 'observations' && (
          <div className="h-full overflow-y-auto">
            <div className="space-y-2">
              {observations.map((obs, i) => (
                <motion.div
                  key={obs.created_at + i}
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.02 }}
                  className="border border-sgc-border bg-[rgba(0,243,255,0.02)] p-3"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sgc-primary font-sans font-bold text-sm tracking-wider">{obs.app}</span>
                    <span className="text-sgc-dim font-mono text-[10px]">
                      {obs.created_at ? new Date(obs.created_at).toLocaleString() : ''}
                    </span>
                  </div>
                  <div className="font-mono text-xs text-sgc-secondary">{obs.content}</div>
                  {obs.keywords && (
                    <div className="flex gap-1 mt-1.5 flex-wrap">
                      {obs.keywords.split(',').filter(Boolean).map((kw, j) => (
                        <span key={j} className="text-[10px] font-mono text-sgc-dim border border-sgc-border px-1.5 py-0.5">
                          {kw.trim()}
                        </span>
                      ))}
                    </div>
                  )}
                </motion.div>
              ))}
              {observations.length === 0 && (
                <div className="flex items-center justify-center h-32 font-mono text-sm text-sgc-dim">
                  No observations yet — the vision loop captures every 5 minutes
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'memory' && (
          <div className="h-full flex flex-col">
            <div className="flex gap-2 mb-3 shrink-0">
              <input
                className="flex-1 bg-[rgba(0,243,255,0.05)] border border-sgc-border text-sgc-primary font-mono text-sm px-3.5 py-2 outline-none focus:border-sgc-border-bright"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && searchMemory()}
                placeholder="Search visual memory..."
              />
              <Button size="sm" onClick={searchMemory} disabled={searching}>
                <Search size={14} className="mr-1" /> {searching ? 'Searching...' : 'Search'}
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2">
              <AnimatePresence>
                {searchResults.length === 0 && searchQuery && (
                  <div className="font-mono text-xs text-sgc-dim">No results found</div>
                )}
                {searchResults.length === 0 && !searchQuery && (
                  <div className="flex items-center justify-center h-32 font-mono text-sm text-sgc-dim">
                    Search your visual memory — what was on your screen?
                  </div>
                )}
                {searchResults.map((r, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    className="border border-sgc-border bg-[rgba(0,243,255,0.02)] p-3"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sgc-primary font-sans font-bold text-sm">{r.app}</span>
                      <span className="text-sgc-dim font-mono text-[10px]">
                        {r.timestamp ? new Date(r.timestamp).toLocaleString() : ''}
                      </span>
                    </div>
                    <div className="font-mono text-xs text-sgc-secondary">{r.content}</div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
