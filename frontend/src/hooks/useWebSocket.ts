import { useCallback, useEffect, useRef, useState } from 'react'

export interface WsEvent {
  type: string
  payload: Record<string, unknown>
}

export interface AssistantStatus {
  state: string
  listening: boolean
  thinking: boolean
  speaking: boolean
  lastCommand: string
  lastResponse: string
  confidence: number
  currentAgent: string
}

const INITIAL_STATUS: AssistantStatus = {
  state: 'IDLE',
  listening: false,
  thinking: false,
  speaking: false,
  lastCommand: '',
  lastResponse: '',
  confidence: 100,
  currentAgent: '',
}

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

function reduceStatus(s: AssistantStatus, data: WsEvent): AssistantStatus {
  switch (data.type) {
    case 'StateChangedEvent': {
      const newState = data.payload.new_state as string
      return {
        ...s,
        state: newState,
        listening: newState === 'LISTENING',
        thinking: newState === 'THINKING',
        speaking: newState === 'SPEAKING',
      }
    }
    case 'CommandTranscribed':
      return { ...s, lastCommand: data.payload.text as string }
    case 'SpokenResponse':
      return { ...s, lastResponse: data.payload.text as string }
    case 'Executed':
      return {
        ...s,
        confidence: (data.payload.confidence as number) ?? s.confidence,
      }
    case 'InternalAgentEvent':
      return { ...s, currentAgent: data.payload.agent_name as string }
    default:
      return s
  }
}

export function useWebSocket() {
  const [status, setStatus] = useState<AssistantStatus>(INITIAL_STATUS)
  const [systemStats, setSystemStats] = useState<SystemStats>(INITIAL_STATS)
  const [events, setEvents] = useState<WsEvent[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const maxEvents = 200

  const connect = useCallback(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = location.host
    const url = `${protocol}//${host}/ws/ui`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => console.log('[WS] connected')
    ws.onclose = () => {
      console.log('[WS] disconnected, reconnecting in 3s')
      setTimeout(connect, 3000)
    }
    ws.onerror = () => ws.close()

    ws.onmessage = (msg) => {
      try {
        const data: WsEvent = JSON.parse(msg.data)
        setEvents((prev) => [...prev.slice(-maxEvents + 1), data])
        setStatus((s) => reduceStatus(s, data))
        
        if (data.type === 'SystemStatsEvent') {
          setSystemStats(data.payload as unknown as SystemStats)
        }
      } catch {
        /* ignore */
      }
    }
  }, [])

  useEffect(() => {
    connect()
    return () => wsRef.current?.close()
  }, [connect])

  return { status, events, systemStats }
}
