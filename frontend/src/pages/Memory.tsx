import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Filter, Tag, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface MemoryEntry {
  content: string
  type?: string
  timestamp?: string
  source?: string
  importance?: number
  confidence?: number
  tags?: string[]
  relevance_pct?: number
  scores?: {
    semantic?: number
    temporal?: number
    importance?: number
    confidence?: number
    access_boost?: number
    combined?: number
  }
  explanation?: string
}

type Tab = 'recent' | 'search'
type SinceOpt = 'all' | '1d' | '7d' | '30d'

// Colour bands for the relevance chip so a glance tells you "great match"
// vs "weak match" without reading the number.
function relevanceColor(pct: number): string {
  if (pct >= 65) return 'text-[#00ff41] border-[#00ff41] bg-[rgba(0,255,65,0.06)]'
  if (pct >= 45) return 'text-sgc-border-bright border-sgc-border-bright bg-[rgba(0,229,255,0.06)]'
  if (pct >= 25) return 'text-sgc-warn border-sgc-warn bg-[rgba(255,175,0,0.06)]'
  return 'text-sgc-dim border-sgc-border'
}

function sinceCutoff(opt: SinceOpt): number | null {
  const now = Date.now()
  if (opt === '1d') return now - 24 * 3600 * 1000
  if (opt === '7d') return now - 7 * 24 * 3600 * 1000
  if (opt === '30d') return now - 30 * 24 * 3600 * 1000
  return null
}

export function Memory() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<MemoryEntry[]>([])
  const [recent, setRecent] = useState<MemoryEntry[]>([])
  const [searching, setSearching] = useState(false)
  const [tab, setTab] = useState<Tab>('recent')
  const [expanded, setExpanded] = useState<number | null>(null)

  // Filters
  const [filterType, setFilterType] = useState<string>('all')
  const [filterSource, setFilterSource] = useState<string>('all')
  const [filterSince, setFilterSince] = useState<SinceOpt>('all')

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
      const res = await fetch(`/memory/search?q=${encodeURIComponent(query)}&limit=20`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      setResults(data.results || [])
    } catch {
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  const raw = tab === 'recent' ? recent : results

  // Available filter values change with the current dataset — don't offer
  // "type = pattern" if the current results have no patterns to filter on.
  const availableTypes = useMemo(
    () => Array.from(new Set(raw.map((e) => e.type).filter(Boolean) as string[])).sort(),
    [raw]
  )
  const availableSources = useMemo(
    () => Array.from(new Set(raw.map((e) => e.source).filter(Boolean) as string[])).sort(),
    [raw]
  )

  const filtered = useMemo(() => {
    const cutoff = sinceCutoff(filterSince)
    return raw.filter((e) => {
      if (filterType !== 'all' && e.type !== filterType) return false
      if (filterSource !== 'all' && e.source !== filterSource) return false
      if (cutoff !== null && e.timestamp) {
        const ts = new Date(e.timestamp).getTime()
        if (isNaN(ts) || ts < cutoff) return false
      }
      return true
    })
  }, [raw, filterType, filterSource, filterSince])

  const activeFilters = (filterType !== 'all' ? 1 : 0) + (filterSource !== 'all' ? 1 : 0) + (filterSince !== 'all' ? 1 : 0)

  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Memory</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Semantic Long-Term Memory</span>
        <span className="ml-auto font-mono text-[10px] text-sgc-dim tracking-wider">
          {filtered.length} / {raw.length} shown
        </span>
      </div>

      <div className="flex gap-0 mb-3 border-b border-sgc-border shrink-0">
        <TabBtn active={tab === 'recent'} onClick={() => setTab('recent')}>Recent</TabBtn>
        <TabBtn active={tab === 'search'} onClick={() => setTab('search')}>Search</TabBtn>
      </div>

      <div className="flex gap-2 mb-3 shrink-0">
        <input
          className="flex-1 bg-[rgba(0,243,255,0.05)] border border-sgc-border text-sgc-primary font-mono text-sm px-3.5 py-2.5 outline-none focus:border-sgc-border-bright"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search()}
          placeholder="Search memories…"
        />
        <Button size="sm" onClick={search} disabled={searching}>
          <Search size={14} className="mr-1" /> {searching ? 'Searching…' : 'Search'}
        </Button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-3 shrink-0 flex-wrap">
        <div className="flex items-center gap-1 text-sgc-dim">
          <Filter size={11} />
          <span className="font-mono text-[10px] tracking-wider uppercase">Filter</span>
          {activeFilters > 0 && <span className="font-mono text-[10px] text-sgc-border-bright">· {activeFilters}</span>}
        </div>
        <FilterSelect label="type" value={filterType} onChange={setFilterType} options={['all', ...availableTypes]} />
        <FilterSelect label="source" value={filterSource} onChange={setFilterSource} options={['all', ...availableSources]} />
        <FilterSelect label="since" value={filterSince} onChange={(v) => setFilterSince(v as SinceOpt)} options={['all', '1d', '7d', '30d']} />
        {activeFilters > 0 && (
          <button
            onClick={() => { setFilterType('all'); setFilterSource('all'); setFilterSince('all') }}
            className="font-mono text-[10px] text-sgc-dim hover:text-sgc-danger tracking-wider uppercase"
          >
            reset
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-2">
        <AnimatePresence>
          {filtered.length === 0 && (
            <div className="font-mono text-xs text-sgc-dim italic">
              {raw.length === 0
                ? (tab === 'recent' ? 'No recent memories yet' : 'Run a search to see results')
                : 'No results match the current filters — reset or widen the criteria'}
            </div>
          )}
          {filtered.map((r, i) => {
            const isOpen = expanded === i
            const pct = r.relevance_pct
            return (
              <motion.div
                key={`${tab}-${i}`}
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                className="border bg-[rgba(0,243,255,0.03)]"
                style={{ borderColor: i === 0 && tab === 'search' ? 'var(--sgc-border-bright)' : 'var(--sgc-border)' }}
              >
                <button
                  className="w-full text-left px-3 py-2.5 hover:bg-[rgba(0,243,255,0.04)] transition-colors cursor-pointer"
                  onClick={() => setExpanded(isOpen ? null : i)}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-xs text-sgc-primary leading-relaxed">
                        {r.content}
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 font-mono text-[10px] text-sgc-dim">
                        {r.type && <span className="text-sgc-secondary">{r.type}</span>}
                        {r.source && <span>from {r.source}</span>}
                        {r.timestamp && <span>{new Date(r.timestamp).toLocaleString()}</span>}
                        {r.tags && r.tags.length > 0 && (
                          <span className="flex items-center gap-1 text-sgc-secondary">
                            <Tag size={9} />
                            {r.tags.slice(0, 3).join(', ')}
                            {r.tags.length > 3 && `+${r.tags.length - 3}`}
                          </span>
                        )}
                      </div>
                    </div>
                    {tab === 'search' && pct !== undefined && (
                      <span className={`font-mono text-[10px] tracking-wider px-2 py-0.5 border shrink-0 ${relevanceColor(pct)}`}>
                        {pct.toFixed(0)}%
                      </span>
                    )}
                  </div>
                </button>

                {/* Score breakdown — only useful for search results */}
                <AnimatePresence>
                  {isOpen && tab === 'search' && r.scores && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="px-3 pb-3 pt-1 border-t border-sgc-border space-y-2">
                        <div className="flex items-center gap-1.5">
                          <Info size={11} className="text-sgc-primary" />
                          <span className="font-mono text-[10px] text-sgc-dim tracking-wider uppercase">Score breakdown</span>
                        </div>
                        <div className="grid grid-cols-5 gap-2 font-mono text-[10px]">
                          <ScoreCell label="semantic"   value={r.scores.semantic} />
                          <ScoreCell label="temporal"   value={r.scores.temporal} />
                          <ScoreCell label="importance" value={r.scores.importance} />
                          <ScoreCell label="confidence" value={r.scores.confidence} />
                          <ScoreCell label="access"     value={r.scores.access_boost} />
                        </div>
                        {r.explanation && (
                          <div className="font-mono text-[10px] text-sgc-secondary italic pt-1 border-t border-sgc-border/50">
                            {r.explanation}
                          </div>
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </div>
  )
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      className={`font-sans text-sm font-semibold tracking-wider px-4 py-2 border-b-2 bg-transparent ${
        active ? 'text-sgc-border-bright border-sgc-border-bright' : 'text-sgc-dim border-transparent hover:text-sgc-secondary'
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

function FilterSelect({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: string[]
}) {
  return (
    <label className="flex items-center gap-1 font-mono text-[10px] tracking-wider uppercase text-sgc-dim">
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-[rgba(0,243,255,0.05)] border border-sgc-border text-sgc-primary px-1.5 py-0.5 font-mono text-[10px] outline-none focus:border-sgc-border-bright cursor-pointer"
      >
        {options.map((o) => (
          <option key={o} value={o} className="bg-sgc-bg text-sgc-primary">{o}</option>
        ))}
      </select>
    </label>
  )
}

function ScoreCell({ label, value }: { label: string; value?: number }) {
  const pct = value !== undefined ? Math.round(value * 100) : 0
  const heat = pct > 70 ? 'text-[#00ff41]' : pct > 40 ? 'text-sgc-border-bright' : 'text-sgc-dim'
  return (
    <div className="flex flex-col gap-0.5">
      <div className="text-sgc-dim uppercase tracking-wider">{label}</div>
      <div className={`${heat} tabular-nums`}>{pct}%</div>
      <div className="h-0.5 bg-[rgba(0,229,255,0.05)] relative overflow-hidden">
        <div
          className={pct > 70 ? 'bg-[#00ff41] h-full' : pct > 40 ? 'bg-sgc-border-bright h-full' : 'bg-sgc-dim h-full'}
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      </div>
    </div>
  )
}
