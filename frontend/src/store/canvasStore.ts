import { create } from 'zustand'

/**
 * Phase 3 — canvas widget state.
 *
 * The types here MUST mirror `backend/core/tools/canvas.py`'s pydantic
 * schema. If the backend adds a widget type, add it here and to
 * `WidgetRenderer` — anything the renderer doesn't recognise falls back
 * to a safe placeholder, never raw content.
 */

export type MetricWidget = {
  type: 'metric'
  id: string
  title: string
  value: number | string
  delta?: number | null
  delta_pct?: number | null
  unit?: string
  source?: string
  fetched_at?: string
  stale?: boolean
}

export type ListItem = { text: string; subtitle?: string }
export type ListWidget = {
  type: 'list'
  id: string
  title: string
  items: ListItem[]
  source?: string
  fetched_at?: string
  stale?: boolean
}

export type MapWidget = {
  type: 'map'
  id: string
  title: string
  embed_url: string  // backend-allowlisted domain (openstreetmap.org)
  lat?: number | null
  lon?: number | null
  source?: string
  fetched_at?: string
  stale?: boolean
}

export type ChartPoint = { x: string; y: number }
export type ChartWidget = {
  type: 'chart'
  id: string
  title: string
  series: ChartPoint[]
  unit?: string
  source?: string
  fetched_at?: string
  stale?: boolean
}

export type TextWidget = {
  type: 'text'
  id: string
  title: string
  body: string
  source?: string
  fetched_at?: string
  stale?: boolean
}

export type Widget = MetricWidget | ListWidget | MapWidget | ChartWidget | TextWidget

interface CanvasState {
  widgets: Widget[]
  lastUpdate: string | null
  setWidgets: (w: Widget[]) => void
  clear: () => void
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
}

export const useCanvasStore = create<CanvasState>((set) => ({
  widgets: [],
  lastUpdate: null,

  setWidgets: (w) => set({ widgets: w, lastUpdate: new Date().toISOString() }),
  clear: () => set({ widgets: [], lastUpdate: null }),

  updateFromWs: (type, payload) => {
    if (type !== 'canvas_update') return
    const raw = (payload?.widgets ?? []) as unknown
    if (!Array.isArray(raw)) return
    // Trust the backend's already-validated shape. We do NOT re-validate
    // here — the strict pydantic pass ran server-side before the event.
    // Anything malformed slipping through renders as an "unsupported
    // widget" placeholder (see WidgetRenderer).
    set({ widgets: raw as Widget[], lastUpdate: new Date().toISOString() })
  },
}))
