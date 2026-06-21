import { create } from 'zustand'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

interface ChatState {
  state: string
  listening: boolean
  thinking: boolean
  speaking: boolean
  lastCommand: string
  lastResponse: string
  confidence: number
  lastTool: string
  lastMemoryHit: string
  messages: ChatMessage[]
  appendMessage: (msg: ChatMessage) => void
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  state: 'IDLE',
  listening: false,
  thinking: false,
  speaking: false,
  lastCommand: '',
  lastResponse: '',
  confidence: 100,
  lastTool: '',
  lastMemoryHit: '',
  messages: [],

  appendMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  updateFromWs: (type, payload) => {
    switch (type) {
      case 'state_changed': {
        const newState = payload.new_state as string
        set({
          state: newState,
          listening: newState === 'LISTENING',
          thinking: newState === 'THINKING',
          speaking: newState === 'SPEAKING',
        })
        break
      }
      case 'command_transcribed':
        set({ lastCommand: payload.text as string })
        break
      case 'spoken_response':
        set({ lastResponse: payload.text as string })
        break
      case 'tool_finished':
        set({
          confidence: (payload.confidence as number) ?? get().confidence,
          lastTool: (payload.tool_name as string) || (payload.command as string) || '',
        })
        break
      case 'tool_started':
        set({ lastTool: payload.tool_name as string })
        break
      case 'agent_status':
        set({ lastTool: payload.agent_name as string })
        break
      case 'memory_hit':
        set({ lastMemoryHit: payload.query as string })
        break
    }
  },
}))
