import { motion, AnimatePresence } from 'framer-motion'
import type { AssistantStatus, SystemStats, WsEvent } from '@/hooks/useWebSocket'

interface Props {
  status: AssistantStatus
  systemStats: SystemStats
  events?: WsEvent[]
}

export function StatusPanel({ status, systemStats, events = [] }: Props) {
  const {
    cpu_percent = 0,
    memory_percent = 0,
    memory_used_gb = 0,
    memory_total_gb = 0,
    disk_percent = 0,
    disk_used_gb = 0,
    disk_total_gb = 0,
    net_down_bps = 0,
    net_up_bps = 0
  } = systemStats || {};

  const stateColor: Record<string, string> = {
    IDLE: 'text-sgc-secondary',
    LISTENING: 'text-sgc-warn',
    THINKING: 'text-sgc-border-bright',
    SPEAKING: 'text-[#00ff41]',
  };

  const recentEvents = events.slice(-8).reverse();

  return (
    <aside className="w-[260px] border-l border-sgc-border-bright flex flex-col overflow-y-auto bg-[rgba(0,229,255,0.02)]">
      {/* Assistant Status */}
      <div className="border-b border-sgc-border p-3">
        <h3 className="font-mono text-[10px] text-sgc-secondary tracking-wider mb-3">ASSISTANT STATUS</h3>
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">STATE</span>
            <motion.span
              key={status.state}
              className={`font-mono text-sm ${stateColor[status.state] || 'text-sgc-secondary'}`}
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
            >
              {status.state || 'IDLE'}
            </motion.span>
          </div>
          <div className="flex justify-between items-center">
            <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">AGENT</span>
            <span className="font-mono text-sm text-sgc-bright">{status.currentAgent || '\u2014'}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">CONFIDENCE</span>
            <span className="font-mono text-sm text-sgc-bright">{status.confidence?.toFixed(0) || '\u2014'}%</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">MEMORY HITS</span>
            <span className="font-mono text-sm text-sgc-bright">{events.filter(e => e.type === 'state_changed').length}</span>
          </div>
        </div>
      </div>

      {/* System Monitor */}
      <div className="border-b border-sgc-border p-3">
        <h3 className="font-mono text-[10px] text-sgc-secondary tracking-wider mb-3">SYSTEM MONITOR</h3>
        <div className="space-y-3">
          <Meter label="CPU" value={cpu_percent} />
          <Meter label="MEMORY" value={memory_percent} sub={`${memory_used_gb} / ${memory_total_gb} GiB`} />
          <Meter label="DISK" value={disk_percent} sub={`${disk_used_gb} / ${disk_total_gb} GiB`} />
          <div className="flex justify-between items-center">
            <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">NETWORK</span>
            <span className="font-mono text-[10px] text-sgc-bright">
              <span className="text-sgc-secondary">↓</span> {net_down_bps.toFixed(1)} <span className="text-sgc-secondary">↑</span> {net_up_bps.toFixed(1)}
            </span>
          </div>
        </div>
      </div>

      {/* Live Events */}
      <div className="p-3 flex-1 min-h-0">
        <h3 className="font-mono text-[10px] text-sgc-secondary tracking-wider mb-3">LIVE EVENTS</h3>
        <div className="space-y-1 font-mono text-[10px]">
          <AnimatePresence>
            {recentEvents.length === 0 && (
              <div className="text-sgc-secondary">Waiting for events...</div>
            )}
            {recentEvents.map((e, i) => (
              <motion.div
                key={e.timestamp + i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                className="truncate"
              >
                <span className="text-sgc-secondary">{e.type.replace(/_/g, ' ')}</span>
                <span className="text-sgc-secondary ml-1">
                  {String(e.payload?.text || e.payload?.action || e.payload?.agent_name || '')}
                </span>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </aside>
  )
}

function Meter({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="font-mono text-[9px] text-sgc-secondary tracking-wider">{label}</span>
        <span className="font-mono text-[10px] text-sgc-bright">{value}%</span>
      </div>
      {sub && <div className="font-mono text-[9px] text-sgc-secondary mb-1">{sub}</div>}
      <div className="h-1.5 bg-sgc-border rounded-full overflow-hidden">
        <motion.div
          className="h-full bg-sgc-border-bright rounded-full shadow-[0_0_4px_#00f3ff]"
          initial={{ width: 0 }}
          animate={{ width: `${value}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
      </div>
    </div>
  )
}
