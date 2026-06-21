import { create } from 'zustand'

export interface AgentEntry {
  name: string
  status: string
  current_action: string | null
  is_thinking: boolean
  reasoning: string
  tools: { tool: string; args: unknown; result: string; latency_ms: number; timestamp: string }[]
  confidence: number
  latency_ms: number
  summary: string | null
  last_seen: string
  details: Record<string, unknown>
}

interface AgentState {
  agents: AgentEntry[]
  activeAgent: string | null
  setAgents: (agents: AgentEntry[], active: string | null) => void
  updateFromWs: (type: string, payload: Record<string, unknown>) => void
}

export const useAgentStore = create<AgentState>((set, get) => ({
  agents: [],
  activeAgent: null,

  setAgents: (agents, active) => set({ agents, activeAgent: active }),

  updateFromWs: (type, payload) => {
    const { agents } = get()
    const name = payload.agent_name as string
    if (!name) return

    let updated = [...agents]
    let idx = updated.findIndex((a) => a.name === name)
    if (idx === -1) {
      idx = updated.length
      updated.push({
        name,
        status: 'standby',
        current_action: null,
        is_thinking: false,
        reasoning: '',
        tools: [],
        confidence: 100,
        latency_ms: 0,
        summary: null,
        last_seen: new Date().toISOString(),
        details: {},
      })
    }

    switch (type) {
      case 'agent_status':
        updated[idx] = {
          ...updated[idx],
          current_action: payload.action as string,
          details: payload.details as Record<string, unknown>,
          last_seen: new Date().toISOString(),
        }
        break
      case 'agent_thinking':
        updated[idx] = {
          ...updated[idx],
          is_thinking: payload.is_thinking as boolean,
          status: payload.is_thinking ? 'thinking' : 'standby',
          last_seen: new Date().toISOString(),
        }
        break
      case 'agent_reasoning':
        updated[idx] = {
          ...updated[idx],
          reasoning: payload.reasoning as string,
          status: 'thinking',
          last_seen: new Date().toISOString(),
        }
        break
      case 'agent_tool_call':
        updated[idx] = {
          ...updated[idx],
          tools: [
            ...updated[idx].tools,
            {
              tool: payload.tool as string,
              args: payload.args as unknown,
              result: payload.result as string,
              latency_ms: (payload.latency_ms as number) || 0,
              timestamp: new Date().toISOString(),
            },
          ],
          current_action: `Tool: ${payload.tool}`,
          last_seen: new Date().toISOString(),
        }
        break
      case 'agent_completed':
        updated[idx] = {
          ...updated[idx],
          status: payload.status as string,
          confidence: (payload.confidence as number) ?? updated[idx].confidence,
          latency_ms: (payload.latency_ms as number) || 0,
          summary: payload.summary as string | null,
          is_thinking: false,
          current_action: null,
          last_seen: new Date().toISOString(),
        }
        break
    }

    const active = updated.find((a) => a.is_thinking)?.name ?? null
    set({ agents: updated, activeAgent: active })
  },
}))
