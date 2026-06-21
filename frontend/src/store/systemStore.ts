import { create } from 'zustand'

export interface SystemStats {
  cpu_percent: number
  memory_percent: number
  memory_used_gb: number
  memory_total_gb: number
  disk_percent: number
  disk_used_gb: number
  disk_total_gb: number
  net_down_bps: number
  net_up_bps: number
  temp_c: number | null
}

const INITIAL_STATS: SystemStats = {
  cpu_percent: 0,
  memory_percent: 0,
  memory_used_gb: 0,
  memory_total_gb: 0,
  disk_percent: 0,
  disk_used_gb: 0,
  disk_total_gb: 0,
  net_down_bps: 0,
  net_up_bps: 0,
  temp_c: null,
}

interface SystemState {
  stats: SystemStats
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
}

export const useSystemStore = create<SystemState>((set) => ({
  stats: INITIAL_STATS,

  updateFromWs: (type, payload) => {
    if (type === 'system_stats') {
      set({ stats: payload as unknown as SystemStats })
    }
  },
}))
