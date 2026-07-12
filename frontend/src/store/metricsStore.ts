import { create } from 'zustand'
import type { AIMetrics } from './telemetry'

interface MetricsState {
  metrics: AIMetrics | null
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
}

// Single source of truth for live AI performance telemetry (ai_metrics event).
export const useMetricsStore = create<MetricsState>((set) => ({
  metrics: null,

  updateFromWs: (type, payload) => {
    if (type === 'ai_metrics') {
      set({ metrics: payload as unknown as AIMetrics })
    }
  },
}))
