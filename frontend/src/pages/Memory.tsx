import { useState, useEffect } from 'react'

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
    <div className="page">
      <div className="page-header">
        <h1>Memory</h1>
        <span className="page-subtitle">Semantic Long-Term Memory</span>
      </div>
      <div className="memory-tabs">
        <button className={`memory-tab ${tab === 'recent' ? 'active' : ''}`} onClick={() => setTab('recent')}>
          Recent
        </button>
        <button className={`memory-tab ${tab === 'search' ? 'active' : ''}`} onClick={() => setTab('search')}>
          Search
        </button>
      </div>
      <div className="memory-search-bar">
        <input
          className="memory-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search()}
          placeholder="Search memories..."
        />
        <button className="memory-search-btn" onClick={search} disabled={searching}>
          {searching ? 'Searching...' : 'Search'}
        </button>
      </div>
      <div className="memory-results">
        {displayEntries.length === 0 && (
          <div className="text-secondary" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            {tab === 'recent' ? 'No recent memories' : 'No results — try a search'}
          </div>
        )}
        {displayEntries.map((r, i) => (
          <div key={i} className="memory-card">
            {r.content}
            {r.timestamp && (
              <div className="memory-meta">
                {r.source && <span className="memory-source">{r.source}</span>}
                <span className="memory-time">{new Date(r.timestamp).toLocaleString()}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
