import { create } from 'zustand'
import type { MemoryHitItem } from './telemetry'

interface MemoryState {
  lastHit: string
  lastHitAt: number | null
  hitCount: number
  hits: MemoryHitItem[]
  results: { content: string; source: string; timestamp: string }[]
  searchResults: { content: string; source: string; timestamp: string; relevance: number }[]
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
  setSearchResults: (results: MemoryState['searchResults']) => void
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  lastHit: '',
  lastHitAt: null,
  hitCount: 0,
  hits: [],
  results: [],
  searchResults: [],

  updateFromWs: (type, payload) => {
    if (type === 'memory_hit') {
      const raw = payload.hits as MemoryHitItem[] | undefined
      const hits = (raw ?? []).map((h) => ({
        title: String(h?.title ?? ''),
        score: Number(h?.score ?? 0),
        source: String(h?.source ?? 'unknown'),
      }))
      set({
        lastHit: payload.query as string,
        lastHitAt: Date.now(),
        hitCount: get().hitCount + 1,
        hits,
      })
    }
  },

  setSearchResults: (results) => set({ searchResults: results }),
}))
