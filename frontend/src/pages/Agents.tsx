import { motion } from 'framer-motion'
import type { AssistantStatus } from '@/hooks/useWebSocket'

interface Props {
  status: AssistantStatus
}

const agents = ['Commander', 'Planner', 'Guardian', 'Operator', 'Watcher']

export function Agents({ status }: Props) {
  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Agents</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Multi-Agent System</span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
        {agents.map((agent) => {
          const active = status.currentAgent?.toLowerCase() === agent.toLowerCase()
          return (
            <motion.div
              key={agent}
              className={`border p-4 flex flex-col gap-2 bg-[rgba(0,243,255,0.03)] ${
                active ? 'border-sgc-border-bright shadow-[0_0_15px_rgba(0,243,255,0.15)]' : 'border-sgc-border'
              }`}
              whileHover={{ scale: 1.02 }}
            >
              <div className="font-sans text-base font-bold text-sgc-bright tracking-wider">{agent}</div>
              <div className="font-mono text-[11px] text-sgc-secondary flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-[#00ff41] shadow-[0_0_6px_#00ff41]' : 'bg-sgc-dim'}`} />
                {active ? 'Active' : 'Standby'}
              </div>
              {active && (
                <span className="font-mono text-[9px] text-sgc-bg bg-sgc-border-bright px-2 py-0.5 tracking-wider self-start">
                  CURRENT
                </span>
              )}
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
