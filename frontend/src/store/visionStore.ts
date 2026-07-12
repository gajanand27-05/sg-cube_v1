import { create } from 'zustand'
import type { VisionObject } from './telemetry'

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
  objects: VisionObject[]
  ocr: string[]
  observations: Observation[]
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
  setWindows: (windows: string[], active: string) => void
  setObservations: (obs: Observation[]) => void
}

export const useVisionStore = create<VisionState>((set) => ({
  lastDescription: '',
  windows: [],
  activeWindow: '',
  objects: [],
  ocr: [],
  observations: [],

  updateFromWs: (type, payload) => {
    if (type === 'vision_update') {
      set({
        lastDescription: payload.description as string,
        windows: (payload.windows as string[]) ?? [],
        objects: (payload.objects as VisionObject[]) ?? [],
        ocr: (payload.ocr as string[]) ?? [],
      })
    }
  },

  setWindows: (windows, active) => set({ windows, activeWindow: active }),
  setObservations: (observations) => set({ observations }),
}))
