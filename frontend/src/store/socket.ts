import { create } from 'zustand'
import { useAgentStore } from './agentStore'
import { useChatStore } from './chatStore'
import { useSystemStore } from './systemStore'
import { useVisionStore } from './visionStore'
import { useMemoryStore } from './memoryStore'

export interface WsEvent {
  type: string
  timestamp: string
  payload: Record<string, unknown>
}

interface SocketState {
  ws: WebSocket | null
  connected: boolean
  events: WsEvent[]
  connect: () => void
  disconnect: () => void
}

export const useSocketStore = create<SocketState>((set, get) => ({
  ws: null,
  connected: false,
  events: [],

  connect: () => {
    const existing = get().ws
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
      return
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = location.host
    const url = `${protocol}//${host}/ws/ui`

    const ws = new WebSocket(url)
    set({ ws, connected: false })

    ws.onopen = () => {
      console.log('[socket] connected')
      set({ connected: true })
    }

    ws.onclose = () => {
      console.log('[socket] disconnected, reconnecting in 3s')
      set({ ws: null, connected: false })
      setTimeout(() => get().connect(), 3000)
    }

    ws.onerror = () => ws.close()

    ws.onmessage = (msg) => {
      try {
        const data: WsEvent = JSON.parse(msg.data)
        set((s) => ({
          events: s.events.length > 500
            ? [...s.events.slice(1), data]
            : [...s.events, data],
        }))
        // Dispatch to data stores
        useAgentStore.getState().updateFromWs(data.type, data.payload)
        useChatStore.getState().updateFromWs(data.type, data.payload)
        useSystemStore.getState().updateFromWs(data.type, data.payload)
        useVisionStore.getState().updateFromWs(data.type, data.payload)
        useMemoryStore.getState().updateFromWs(data.type, data.payload)
      } catch {
        /* ignore */
      }
    }
  },

  disconnect: () => {
    get().ws?.close()
    set({ ws: null, connected: false })
  },
}))
