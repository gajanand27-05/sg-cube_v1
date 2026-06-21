import { create } from 'zustand'

export interface Observation {
  content: string
  app: string
  keywords: string
  created_at: string
}

interface VisionState {
  lastDescription: string
  windows: string[]
  activeWindow: string
  observations: Observation[]
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
  setWindows: (windows: string[], active: string) => void
  setObservations: (obs: Observation[]) => void
}

export const useVisionStore = create<VisionState>((set) => ({
  lastDescription: '',
  windows: [],
  activeWindow: '',
  observations: [],

  updateFromWs: (type, payload) => {
    if (type === 'vision_update') {
      set({
        lastDescription: payload.description as string,
        windows: (payload.windows as string[]) ?? [],
      })
    }
  },

  setWindows: (windows, active) => set({ windows, activeWindow: active }),
  setObservations: (observations) => set({ observations }),
}))
