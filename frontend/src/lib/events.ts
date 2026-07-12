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

export type ModuleKey = 'All' | 'Voice' | 'Memory' | 'Tool' | 'Vision' | 'LLM' | 'Error'
export const MODULES: ModuleKey[] = ['All', 'Voice', 'Memory', 'Tool', 'Vision', 'LLM', 'Error']

export function matchModule(type: string, mod: ModuleKey): boolean {
  if (mod === 'All') return true
  if (mod === 'Voice') return type.includes('voice') || type.includes('speech')
  if (mod === 'Memory') return type.includes('memory')
  if (mod === 'Tool') return type.includes('tool')
  if (mod === 'Vision') return type.includes('vision')
  if (mod === 'LLM') return type.includes('llm') || type.includes('reasoning')
  if (mod === 'Error') return type.includes('error')
  return true
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
