import { create } from 'zustand'

interface MemoryState {
  lastHit: string
  results: { content: string; source: string; timestamp: string }[]
  searchResults: { content: string; source: string; timestamp: string; relevance: number }[]
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
  setSearchResults: (results: MemoryState['searchResults']) => void
}

export const useMemoryStore = create<MemoryState>((set) => ({
  lastHit: '',
  results: [],
  searchResults: [],

  updateFromWs: (type, payload) => {
    if (type === 'memory_hit') {
      set({
        lastHit: payload.query as string,
      })
    }
  },

  setSearchResults: (results) => set({ searchResults: results }),
}))
