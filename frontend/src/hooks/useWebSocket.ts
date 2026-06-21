import { useEffect } from 'react'
import { useSocketStore, useChatStore, useSystemStore, useAgentStore } from '@/store'

export type { WsEvent } from '@/store'
export type { SystemStats } from '@/store'

export interface AssistantStatus {
  state: string
  listening: boolean
  thinking: boolean
  speaking: boolean
  lastCommand: string
  lastResponse: string
  confidence: number
  currentAgent: string
  lastTool: string
  lastMemoryHit: string
}

export function useWebSocket() {
  const connect = useSocketStore((s) => s.connect)
  const events = useSocketStore((s) => s.events)
  const connected = useSocketStore((s) => s.connected)

  useEffect(() => {
    connect()
  }, [connect])

  const chat = useChatStore()
  const systemStats = useSystemStore((s) => s.stats)

  const status: AssistantStatus = {
    state: chat.state,
    listening: chat.listening,
    thinking: chat.thinking,
    speaking: chat.speaking,
    lastCommand: chat.lastCommand,
    lastResponse: chat.lastResponse,
    confidence: chat.confidence,
    currentAgent: useAgentStore.getState().activeAgent ?? chat.lastTool,
    lastTool: chat.lastTool,
    lastMemoryHit: chat.lastMemoryHit,
  }

  return { status, systemStats, events, connected }
}
