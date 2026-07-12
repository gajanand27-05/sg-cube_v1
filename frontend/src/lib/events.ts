import type { WsEvent } from '@/hooks/useWebSocket'

export const EVENT_COLORS: Record<string, string> = {
  voice_detected: 'text-[#00ff41] border-[#00ff41]',
  speech_recognition: 'text-[#00ff41] border-[#00ff41]',
  memory_search: 'text-[#a855f7] border-[#a855f7]',
  tool_call: 'text-[#3b82f6] border-[#3b82f6]',
  vision_detected: 'text-[#f97316] border-[#f97316]',
  llm_reasoning: 'text-[#eab308] border-[#eab308]',
  error: 'text-[#ef4444] border-[#ef4444]',
}
export const DEFAULT_COLOR = 'text-[#00aaff] border-[#00aaff]'

// ── Dashboard operational filters (single-select + All) ──────────────────────
export type DashModule = 'All' | 'Voice' | 'AI' | 'Memory' | 'Vision' | 'Tools' | 'Errors'
export const DASH_MODULES: DashModule[] = ['All', 'Voice', 'AI', 'Memory', 'Vision', 'Tools', 'Errors']

export function matchDashModule(type: string, mod: DashModule): boolean {
  if (mod === 'All') return true
  if (mod === 'Voice') return type.includes('voice') || type.includes('speech')
  if (mod === 'AI') return type.includes('llm') || type.includes('reasoning')
  if (mod === 'Memory') return type.includes('memory')
  if (mod === 'Vision') return type.includes('vision')
  if (mod === 'Tools') return type.includes('tool')
  if (mod === 'Errors') return type.includes('error')
  return true
}

// ── System Inspector filters (multi-select, no "All") ────────────────────────
export type InspectorModule =
  | 'Voice' | 'AI' | 'Memory' | 'Vision' | 'Tools' | 'Errors' | 'Warnings' | 'Info'
export const INSPECTOR_MODULES: InspectorModule[] = [
  'Voice', 'AI', 'Memory', 'Vision', 'Tools', 'Errors', 'Warnings', 'Info',
]

export function matchInspectorModule(
  type: string,
  mod: InspectorModule,
  level?: string,
): boolean {
  switch (mod) {
    case 'Voice': return type.includes('voice') || type.includes('speech')
    case 'AI': return type.includes('llm') || type.includes('reasoning')
    case 'Memory': return type.includes('memory')
    case 'Vision': return type.includes('vision')
    case 'Tools': return type.includes('tool')
    case 'Errors': return type.includes('error')
    case 'Warnings': return type.includes('warning') || level === 'warning'
    case 'Info':
      return !(
        type.includes('voice') || type.includes('speech') || type.includes('llm') ||
        type.includes('reasoning') || type.includes('memory') || type.includes('vision') ||
        type.includes('tool') || type.includes('error') || type.includes('warning') || level === 'warning'
      )
  }
}

export function summarizeEvent(e: WsEvent): string {
  const p = e.payload || {}
  if (e.type.includes('voice') || e.type.includes('speech'))
    return String(p.text ?? p.transcript ?? (e.type.includes('detected') ? 'Voice detected' : 'Speech'))
  if (e.type.includes('memory')) return String(p.query ?? p.key ?? 'Memory access')
  if (e.type.includes('tool')) return String(p.function_name ?? p.tool ?? p.action ?? 'Tool call')
  if (e.type.includes('vision')) return String(p.description ?? p.window ?? 'Scene observed')
  if (e.type.includes('llm') || e.type.includes('reasoning')) return String(p.tokens ?? p.model ?? 'LLM reasoning')
  if (e.type.includes('error')) return String(p.message ?? p.error ?? 'Error')
  return ''
}

export function eventDuration(e: WsEvent): number | null {
  const p = e.payload || {}
  const d = p.duration_ms ?? p.latency_ms ?? p.latency ?? p.duration
  return typeof d === 'number' ? d : null
}

export function isActiveEvent(e: WsEvent, now: number, windowMs = 3000): boolean {
  return now - new Date(e.timestamp).getTime() < windowMs
}

// ponytail: trace grouping is heuristic — the backend emits no correlation id
// yet. We segment the chronological stream into "turns" bounded by
// user-initiated start events. Upgrade path: add trace_id/session_id to
// payloads and group by it instead of by proximity.
const TRACE_START = /voice_detected|wake_word|speech_recognition|user_input|user_message|chat_message|prompt/
const TRACE_END = /speaking|response|assistant_response|tts|reply/

export function buildTrace(events: WsEvent[], selected: WsEvent): WsEvent[] {
  const idKey = (p: Record<string, unknown>) => p.trace_id ?? p.session_id ?? p.turn_id
  const selId = idKey(selected.payload || {})
  if (selId != null) {
    const trace = events.filter((e) => idKey(e.payload || {}) === selId)
    if (trace.length > 1) return trace
  }
  const idx = events.findIndex((e) => e.id === selected.id)
  if (idx === -1) return [selected]
  let start = idx
  while (start > 0 && !TRACE_START.test(events[start].type)) start--
  let end = idx
  while (
    end < events.length - 1 &&
    !TRACE_END.test(events[end].type) &&
    !TRACE_START.test(events[end + 1].type)
  ) end++
  if (end < events.length - 1 && TRACE_END.test(events[end].type)) end++
  return events.slice(start, end + 1)
}

export interface EventMetrics {
  latency: number | null
  duration: number | null
  confidence: number | null
  tokens: number | null
  inference: string | null
  model: string | null
}

export function eventMetrics(e: WsEvent): EventMetrics {
  const p = e.payload || {}
  return {
    latency: typeof p.latency_ms === 'number' ? p.latency_ms
      : typeof p.latency === 'number' ? p.latency : null,
    duration: typeof p.duration_ms === 'number' ? p.duration_ms
      : typeof p.duration === 'number' ? p.duration : null,
    confidence: typeof p.confidence === 'number' ? p.confidence : null,
    tokens: typeof p.tokens === 'number' ? p.tokens : null,
    inference: typeof p.inference === 'string' ? p.inference : null,
    model: typeof p.model === 'string' ? p.model : null,
  }
}
