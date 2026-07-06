import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { AssistantStatus, SystemStats } from '@/hooks/useWebSocket'
import { useAgentStore, useSocketStore } from '@/store'

interface Props {
  status: AssistantStatus
  systemStats?: SystemStats
}

// Fixed mapping so the cube face → agent relationship is stable across
// renders. Face labels keep the SG/CUBE branding — the *color* is what
// carries the status signal, driven by agent activity in agentStore.
const FACE_AGENTS = [
  { face: 'front', label: 'SG', agent: 'Commander' },
  { face: 'right', label: 'CUBE', agent: 'Planner' },
  { face: 'back', label: 'SG', agent: 'Guardian' },
  { face: 'left', label: 'CUBE', agent: 'Operator' },
  { face: 'top', label: '', agent: 'Watcher' },
  { face: 'bottom', label: '', agent: 'System' },
] as const

type FaceStatus = 'idle' | 'thinking' | 'completed' | 'failed'

function statusFor(agentName: string, agents: { name: string; status: string; is_thinking: boolean }[]): FaceStatus {
  const a = agents.find((x) => x.name.toLowerCase() === agentName.toLowerCase())
  if (!a) return 'idle'
  if (a.is_thinking) return 'thinking'
  const s = a.status.toLowerCase()
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'completed' || s === 'verified') return 'completed'
  return 'idle'
}

// One inline style per face — the App.css .face rule sets the base look,
// we override just what changes with status.
function faceStyle(status: FaceStatus): React.CSSProperties {
  const map = {
    idle: { border: '#00557755', glow: 'rgba(0, 85, 119, 0.15)', text: '#00557799' },
    thinking: { border: '#00e5ff', glow: 'rgba(0, 229, 255, 0.7)', text: '#ffffff' },
    completed: { border: '#00ff4166', glow: 'rgba(0, 255, 65, 0.35)', text: '#00ff41cc' },
    failed: { border: '#ff003366', glow: 'rgba(255, 0, 51, 0.4)', text: '#ff0033cc' },
  }
  const c = map[status]
  return {
    borderColor: c.border,
    boxShadow: `0 0 30px ${c.glow}, inset 0 0 30px ${c.glow}`,
    color: c.text,
    textShadow: `0 0 15px ${c.glow}`,
    transition: 'border-color 300ms, box-shadow 300ms, color 300ms',
  }
}

// Slim horizontal bar used for CPU / mem / disk in the system monitor.
function StatBar({ label, value, unit = '%' }: { label: string; value: number; unit?: string }) {
  const pct = Math.max(0, Math.min(100, value))
  const heat = pct > 85 ? 'bg-sgc-danger' : pct > 60 ? 'bg-sgc-warn' : 'bg-sgc-border-bright'
  return (
    <div className="flex items-center gap-2 font-mono text-[11px]">
      <span className="text-sgc-dim w-14 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-[rgba(0,229,255,0.05)] border border-sgc-border relative overflow-hidden">
        <motion.div
          className={`h-full ${heat}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      <span className="text-sgc-bright w-14 text-right tabular-nums shrink-0">
        {value.toFixed(1)}{unit}
      </span>
    </div>
  )
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

function formatBytes(bps: number): string {
  if (bps < 1024) return `${bps.toFixed(0)} B/s`
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`
  return `${(bps / 1024 / 1024).toFixed(1)} MB/s`
}

export function Dashboard({ systemStats }: Props) {
  const agents = useAgentStore((s) => s.agents)
  const connected = useSocketStore((s) => s.connected)
  const events = useSocketStore((s) => s.events)

  // Track session uptime from mount. Not the daemon uptime (we'd need a
  // /health-since endpoint for that), but honest: this is how long the
  // dashboard has been watching. Better than the hardcoded "2h 47m" it
  // used to show.
  const [uptime, setUptime] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const id = setInterval(() => setUptime(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(id)
  }, [])

  const stats = systemStats ?? {
    cpu_percent: 0, memory_percent: 0, memory_used_gb: 0, memory_total_gb: 0,
    disk_percent: 0, disk_used_gb: 0, disk_total_gb: 0,
    net_down_bps: 0, net_up_bps: 0, temp_c: null,
  } as SystemStats

  const faceStatuses = useMemo(
    () => FACE_AGENTS.map((f) => ({
      ...f,
      status: f.agent === 'System'
        ? (connected ? 'completed' : 'failed') as FaceStatus
        : statusFor(f.agent, agents),
    })),
    [agents, connected]
  )

  const summary = useMemo(() => {
    const thinking = faceStatuses.filter((f) => f.status === 'thinking').length
    const failed = faceStatuses.filter((f) => f.status === 'failed').length
    const idle = faceStatuses.length - thinking - failed
    return { thinking, idle, failed }
  }, [faceStatuses])

  // Last 5 events from the WS buffer for the activity ticker.
  const recent = events.slice(-5).reverse()

  return (
    <div className="h-full flex overflow-hidden">
      {/* Left column: real system data + agents + activity */}
      <div className="flex-1 flex flex-col gap-4 p-4 overflow-y-auto">

        {/* System monitor — replaces the neofetch mockup */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border flex items-center justify-between">
            <span><span className="text-sgc-border-bright">sgcube</span>:~$ system --live</span>
            <span className="text-sgc-dim">uptime · {formatUptime(uptime)}</span>
          </div>
          <div className="p-3 flex flex-col gap-2">
            <StatBar label="CPU" value={stats.cpu_percent} />
            <StatBar label="MEM" value={stats.memory_percent} />
            <div className="text-[10px] text-sgc-dim pl-16 -mt-1 font-mono">
              {stats.memory_used_gb.toFixed(1)} / {stats.memory_total_gb.toFixed(1)} GiB
            </div>
            <StatBar label="DISK" value={stats.disk_percent} />
            <div className="text-[10px] text-sgc-dim pl-16 -mt-1 font-mono">
              {stats.disk_used_gb.toFixed(0)} / {stats.disk_total_gb.toFixed(0)} GiB
            </div>
            {stats.temp_c !== null && (
              <StatBar label="TEMP" value={stats.temp_c} unit="°C" />
            )}
            <div className="flex items-center gap-2 font-mono text-[11px] pt-1">
              <span className="text-sgc-dim w-14 shrink-0">NET</span>
              <span className="text-sgc-border-bright">↓ {formatBytes(stats.net_down_bps)}</span>
              <span className="text-sgc-dim">·</span>
              <span className="text-sgc-border-bright">↑ {formatBytes(stats.net_up_bps)}</span>
            </div>
          </div>
        </div>

        {/* Agents monitor — replaces the fake service status */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border flex items-center justify-between">
            <span><span className="text-sgc-border-bright">sgcube</span>:~$ agents</span>
            <span className="text-sgc-dim">
              {summary.thinking} active · {summary.idle} idle
              {summary.failed > 0 && <span className="text-sgc-danger"> · {summary.failed} failed</span>}
            </span>
          </div>
          <div className="p-3 flex flex-col gap-1.5">
            {faceStatuses.map((f) => (
              <div key={f.agent} className="flex items-center gap-2 font-mono text-[11px]">
                <motion.span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{
                    background: f.status === 'thinking' ? '#00e5ff'
                      : f.status === 'failed' ? '#ff0033'
                      : f.status === 'completed' ? '#00ff41'
                      : '#005577',
                  }}
                  animate={f.status === 'thinking' ? { opacity: [0.4, 1, 0.4] } : { opacity: 1 }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
                />
                <span className="text-sgc-secondary w-24">{f.agent}</span>
                <span className={
                  f.status === 'thinking' ? 'text-sgc-border-bright'
                  : f.status === 'failed' ? 'text-sgc-danger'
                  : f.status === 'completed' ? 'text-[#00ff41]'
                  : 'text-sgc-dim'
                }>
                  {f.status.toUpperCase()}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Recent activity — from the WS event buffer */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border">
            <span className="text-sgc-border-bright">sgcube</span>:~$ tail --events 5
          </div>
          <div className="p-3 flex flex-col gap-1 min-h-[80px]">
            <AnimatePresence initial={false}>
              {recent.length === 0 && (
                <div className="text-sgc-dim font-mono text-[11px] italic">
                  Waiting for events…
                </div>
              )}
              {recent.map((e, i) => (
                <motion.div
                  key={`${e.timestamp}-${i}`}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center gap-2 font-mono text-[11px]"
                >
                  <span className="text-sgc-dim tabular-nums">
                    {new Date(e.timestamp).toLocaleTimeString('en-US', { hour12: false })}
                  </span>
                  <span className="text-sgc-border-bright">{e.type}</span>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* Right: HUD rings + cube (now with agent-status faces) */}
      <div className="w-[400px] flex items-center justify-center relative overflow-hidden">
        <svg viewBox="0 0 500 500" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
          <circle cx="250" cy="250" r="230" fill="none" stroke="var(--sgc-dim)" strokeWidth="1" opacity="0.3" strokeDasharray="1 10" className="animate-spin-slow origin-center" />
          <circle cx="250" cy="250" r="220" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="1" opacity="0.2" strokeDasharray="5 15" />
          <circle cx="250" cy="250" r="200" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="4" opacity="0.4" strokeDasharray="2 6" className="animate-spin-slow origin-center" style={{ animationDirection: 'reverse' }} />
          <circle cx="250" cy="250" r="200" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="1" opacity="0.3" />
          <circle cx="250" cy="250" r="180" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.1" />
          <circle cx="250" cy="250" r="175" fill="none" stroke="var(--sgc-bright)" strokeWidth="1" opacity="0.3" strokeDasharray="20 40" className="animate-spin-slow origin-center" />
          <circle cx="250" cy="250" r="150" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="3" opacity="0.8" strokeDasharray="80 20 10 20 40 20" className="animate-spin-slow origin-center" />
          <circle cx="250" cy="250" r="145" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="1" opacity="0.5" />
          <circle cx="250" cy="250" r="120" fill="none" stroke="var(--sgc-primary)" strokeWidth="1" opacity="0.6" strokeDasharray="10 5" className="animate-spin-slow origin-center" style={{ animationDirection: 'reverse' }} />
          <line x1="250" y1="0" x2="250" y2="30" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
          <line x1="250" y1="470" x2="250" y2="500" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
          <line x1="0" y1="250" x2="30" y2="250" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
          <line x1="470" y1="250" x2="500" y2="250" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
          <path d="M 100 100 L 120 100 M 100 100 L 100 120" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.6" />
          <path d="M 400 100 L 380 100 M 400 100 L 400 120" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.6" />
          <path d="M 100 400 L 120 400 M 100 400 L 100 380" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.6" />
          <path d="M 400 400 L 380 400 M 400 400 L 400 380" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.6" />
        </svg>
        <div className="absolute flex flex-col items-center gap-6" style={{ perspective: '1200px' }}>
          <div className="cube-container">
            <div className="cube">
              {FACE_AGENTS.map((f) => {
                const status = f.agent === 'System'
                  ? (connected ? 'completed' : 'failed') as FaceStatus
                  : statusFor(f.agent, agents)
                return (
                  <div
                    key={f.face}
                    className={`face ${f.face}`}
                    style={faceStyle(status)}
                  >
                    {f.label}
                  </div>
                )
              })}
            </div>
          </div>
          {/* Legend — decodes the cube for anyone who doesn't have the mapping memorized */}
          <div className="flex flex-col items-center gap-1 font-mono text-[9px] tracking-wider text-sgc-dim">
            <div className="uppercase">agents on cube</div>
            <div className="flex gap-2 text-sgc-secondary">
              <span>Cmd·Pln·Grd·Opr·Wch</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
