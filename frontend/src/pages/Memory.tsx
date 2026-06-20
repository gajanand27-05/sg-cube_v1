import { useState } from 'react'

export function Memory() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<string[]>([])
  const [searching, setSearching] = useState(false)

  const search = async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const res = await fetch(`/memory/search?q=${encodeURIComponent(query)}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      setResults(data.results || [])
    } catch {
      setResults(['Search failed — backend endpoint may not be wired yet'])
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Memory</h1>
        <span className="page-subtitle">Semantic Long-Term Memory</span>
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
        {results.map((r, i) => (
          <div key={i} className="memory-card">
            {r}
          </div>
        ))}
      </div>
    </div>
  )
}
