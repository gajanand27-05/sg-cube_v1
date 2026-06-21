import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface MemoryEntry {
  content: string
  timestamp?: string
  source?: string
  type?: string
}

export function Memory() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<MemoryEntry[]>([])
  const [recent, setRecent] = useState<MemoryEntry[]>([])
  const [searching, setSearching] = useState(false)
  const [tab, setTab] = useState<'recent' | 'search'>('recent')

  useEffect(() => {
    fetch('/memory/recent', { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => setRecent(data.results || []))
      .catch(() => {})
  }, [])

  const search = async () => {
    if (!query.trim()) return
    setSearching(true)
    setTab('search')
    try {
      const res = await fetch(`/memory/search?q=${encodeURIComponent(query)}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      setResults(data.results || [])
    } catch {
      setResults([{ content: 'Search failed' }])
    } finally {
      setSearching(false)
    }
  }

  const displayEntries = tab === 'recent' ? recent : results

  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Memory</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Semantic Long-Term Memory</span>
      </div>

      <div className="flex gap-0 mb-3 border-b border-sgc-border shrink-0">
        <button
          className={`font-sans text-sm font-semibold tracking-wider px-4 py-2 border-b-2 bg-transparent ${
            tab === 'recent' ? 'text-sgc-border-bright border-sgc-border-bright' : 'text-sgc-dim border-transparent hover:text-sgc-secondary'
          }`}
          onClick={() => setTab('recent')}
        >
          Recent
        </button>
        <button
          className={`font-sans text-sm font-semibold tracking-wider px-4 py-2 border-b-2 bg-transparent ${
            tab === 'search' ? 'text-sgc-border-bright border-sgc-border-bright' : 'text-sgc-dim border-transparent hover:text-sgc-secondary'
          }`}
          onClick={() => setTab('search')}
        >
          Search
        </button>
      </div>

      <div className="flex gap-2 mb-4 shrink-0">
        <input
          className="flex-1 bg-[rgba(0,243,255,0.05)] border border-sgc-border text-sgc-primary font-mono text-sm px-3.5 py-2.5 outline-none focus:border-sgc-border-bright"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search()}
          placeholder="Search memories..."
        />
        <Button size="sm" onClick={search} disabled={searching}>
          <Search size={14} className="mr-1" /> {searching ? 'Searching...' : 'Search'}
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-2">
        <AnimatePresence>
          {displayEntries.length === 0 && (
            <div className="font-mono text-xs text-sgc-dim">
              {tab === 'recent' ? 'No recent memories' : 'No results — try a search'}
            </div>
          )}
          {displayEntries.map((r, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              className={`font-mono text-xs px-3 py-2.5 border ${
                i === 0 && tab === 'search'
                  ? 'border-sgc-border-bright text-sgc-bright'
                  : 'border-sgc-border text-sgc-secondary bg-[rgba(0,243,255,0.03)]'
              }`}
            >
              {r.content}
              {r.timestamp && (
                <div className="flex gap-3 mt-1.5 text-[10px] text-sgc-dim">
                  {r.source && <span className="text-sgc-secondary">{r.source}</span>}
                  <span>{new Date(r.timestamp).toLocaleString()}</span>
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  )
}
