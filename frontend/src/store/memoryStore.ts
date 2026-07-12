import { create } from 'zustand'

interface MemoryState {
  lastHit: string
  lastHitAt: number | null
  hitCount: number
  results: { content: string; source: string; timestamp: string }[]
  searchResults: { content: string; source: string; timestamp: string; relevance: number }[]
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
  setSearchResults: (results: MemoryState['searchResults']) => void
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  lastHit: '',
  lastHitAt: null,
  hitCount: 0,
  results: [],
  searchResults: [],

  updateFromWs: (type, payload) => {
    if (type === 'memory_hit') {
      set({
        lastHit: payload.query as string,
        lastHitAt: Date.now(),
        hitCount: get().hitCount + 1,
      })
    }
  },

  setSearchResults: (results) => set({ searchResults: results }),
}))
