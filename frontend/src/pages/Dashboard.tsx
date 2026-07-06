import { useEffect, useMemo, useRef, useState } from 'react'
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

// Backend /diagnostics/inspect returns each tool's source-module basename
// as `category`. Map those raw modules → display buckets for the services
// grid. Anything unmapped falls into "misc" so a new tool module doesn't
// silently vanish from the grid.
const CATEGORY_BUCKETS: Record<string, { bucket: string; color: string }> = {
  shell:        { bucket: 'system',   color: '#00e5ff' },
  windowing:    { bucket: 'system',   color: '#00e5ff' },
  system_info:  { bucket: 'system',   color: '#00e5ff' },
  automation:  { bucket: 'system',   color: '#00e5ff' },
  files:        { bucket: 'files',    color: '#00ff41' },
  file_editor:  { bucket: 'files',    color: '#00ff41' },
  web_reader:   { bucket: 'web',      color: '#0088ff' },
  weather:      { bucket: 'web',      color: '#0088ff' },
  news:         { bucket: 'web',      color: '#0088ff' },
  audio:        { bucket: 'media',    color: '#ff8800' },
  read_aloud:   { bucket: 'media',    color: '#ff8800' },
  ocr:          { bucket: 'media',    color: '#ff8800' },
  display:      { bucket: 'media',    color: '#ff8800' },
  vision:       { bucket: 'media',    color: '#ff8800' },
  summarize:    { bucket: 'ai',       color: '#cc66ff' },
  translate:    { bucket: 'ai',       color: '#cc66ff' },
  memory:       { bucket: 'ai',       color: '#cc66ff' },
  llm_helper:   { bucket: 'ai',       color: '#cc66ff' },
  comms:        { bucket: 'comms',    color: '#ffcc00' },
  reminders:    { bucket: 'comms',    color: '#ffcc00' },
  notes:        { bucket: 'comms',    color: '#ffcc00' },
  game_tools:   { bucket: 'games',    color: '#ff4488' },
  fun:          { bucket: 'games',    color: '#ff4488' },
  finance:      { bucket: 'finance',  color: '#00ffbb' },
  builtins:     { bucket: 'core',     color: '#ffffff' },
}
const BUCKET_ORDER = ['system', 'files', 'web', 'media', 'ai', 'comms', 'games', 'finance', 'core', 'misc']

function statusFor(agentName: string, agents: { name: string; status: string; is_thinking: boolean }[]): FaceStatus {
  const a = agents.find((x) => x.name.toLowerCase() === agentName.toLowerCase())
  if (!a) return 'idle'
  if (a.is_thinking) return 'thinking'
  const s = a.status.toLowerCase()
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'completed' || s === 'verified') return 'completed'
  return 'idle'
}

function faceStyle(status: FaceStatus): React.CSSProperties {
  const map = {
    idle:      { border: '#00557755', glow: 'rgba(0, 85, 119, 0.15)',  text: '#00557799' },
    thinking:  { border: '#00e5ff',   glow: 'rgba(0, 229, 255, 0.7)',   text: '#ffffff' },
    completed: { border: '#00ff4166', glow: 'rgba(0, 255, 65, 0.35)',   text: '#00ff41cc' },
    failed:    { border: '#ff003366', glow: 'rgba(255, 0, 51, 0.4)',    text: '#ff0033cc' },
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

// Live time-series over the last 60 samples (~2 min at telemetry's 2s tick).
// Grid backdrop + smooth polyline + soft fill under the curve.
function Sparkline({ data, label, value, unit = '%', color = '#00e5ff', max }: {
  data: number[]; label: string; value: number; unit?: string; color?: string; max?: number
}) {
  const W = 100
  const H = 28
  const localMax = max ?? Math.max(100, ...data)
  const step = data.length > 1 ? W / (data.length - 1) : W
  const pts = data.map((v, i) => `${(i * step).toFixed(2)},${(H - (v / localMax) * H).toFixed(2)}`).join(' ')
  const area = data.length > 0 ? `0,${H} ${pts} ${W},${H}` : ''

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between font-mono text-[10px] tracking-wider">
        <span className="text-sgc-dim">{label}</span>
        <span className="text-sgc-bright tabular-nums">
          {value.toFixed(1)}{unit}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H * 1.5} preserveAspectRatio="none" className="block">
        {/* grid backdrop — 3 horizontal ticks */}
        {[0.25, 0.5, 0.75].map((y) => (
          <line key={y} x1={0} x2={W} y1={H * y} y2={H * y} stroke="rgba(0,229,255,0.08)" strokeWidth="0.4" />
        ))}
        {data.length > 1 && (
          <>
            <polygon points={area} fill={color} opacity="0.15" />
            <polyline points={pts} fill="none" stroke={color} strokeWidth="1" strokeLinejoin="round" opacity="0.9" />
          </>
        )}
      </svg>
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

const MAX_SAMPLES = 60

interface ToolInfo { name: string; category: string; usage: { calls?: number; errors?: number } }
interface Bucket { name: string; color: string; count: number; used: number }

export function Dashboard({ systemStats }: Props) {
  const agents = useAgentStore((s) => s.agents)
  const connected = useSocketStore((s) => s.connected)
  const events = useSocketStore((s) => s.events)

  const [uptime, setUptime] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const id = setInterval(() => setUptime(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(id)
  }, [])

  // Live history for the sparklines. Local buffer — this dashboard's
  // watching-window, not persisted. Each stat holds the last 60 samples.
  const [cpuHist, setCpuHist] = useState<number[]>([])
  const [memHist, setMemHist] = useState<number[]>([])
  const [diskHist, setDiskHist] = useState<number[]>([])
  const [netHist, setNetHist] = useState<number[]>([])
  const lastStatsRef = useRef<SystemStats | null>(null)

  useEffect(() => {
    if (!systemStats) return
    // Skip if identical to last (e.g. re-render without a new WS tick)
    if (lastStatsRef.current === systemStats) return
    lastStatsRef.current = systemStats
    const push = (setter: (fn: (prev: number[]) => number[]) => void, v: number) =>
      setter((prev) => (prev.length >= MAX_SAMPLES ? [...prev.slice(1), v] : [...prev, v]))
    push(setCpuHist, systemStats.cpu_percent)
    push(setMemHist, systemStats.memory_percent)
    push(setDiskHist, systemStats.disk_percent)
    push(setNetHist, systemStats.net_down_bps + systemStats.net_up_bps)
  }, [systemStats])

  // Fetch tools once at mount, group by display bucket. Refetch every 30s
  // in case a plugin gets loaded live — cheap and keeps the grid honest.
  const [tools, setTools] = useState<ToolInfo[]>([])
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const res = await fetch('/diagnostics/inspect')
        if (!res.ok) return
        const data = await res.json()
        if (alive) setTools(data.tools ?? [])
      } catch { /* silent — grid just shows nothing yet */ }
    }
    load()
    const id = setInterval(load, 30_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const buckets: Bucket[] = useMemo(() => {
    const acc: Record<string, Bucket> = {}
    for (const b of BUCKET_ORDER) {
      const color = Object.values(CATEGORY_BUCKETS).find((v) => v.bucket === b)?.color ?? '#888888'
      acc[b] = { name: b, color, count: 0, used: 0 }
    }
    for (const t of tools) {
      const map = CATEGORY_BUCKETS[t.category] ?? { bucket: 'misc', color: '#888888' }
      const b = acc[map.bucket] ?? (acc[map.bucket] = { name: map.bucket, color: map.color, count: 0, used: 0 })
      b.count += 1
      if ((t.usage?.calls ?? 0) > 0) b.used += 1
    }
    return BUCKET_ORDER.map((n) => acc[n]).filter((b) => b.count > 0)
  }, [tools])

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

  const recent = events.slice(-5).reverse()
  const totalTools = tools.length

  return (
    <div className="h-full flex overflow-hidden">
      {/* LEFT: terminal-style neofetch + agents + activity */}
      <div className="w-[52%] flex flex-col gap-3 p-4 overflow-y-auto">

        {/* Neofetch-style card, but real */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border flex items-center justify-between">
            <span><span className="text-sgc-border-bright">sgcube</span>:~$ neofetch</span>
            <span className="text-sgc-dim">uptime · {formatUptime(uptime)}</span>
          </div>
          <div className="flex gap-4 p-3">
            <pre className="text-sgc-border-bright text-[9px] leading-tight font-mono opacity-70">{`
    .:+oooo+:.
  -/++++++++/-
-oyyyyyyyyyyyyo-
./y:-odNMMMMMNmdo-.:y.
-/yMMMMMMMMMMMMMMMMMxyy--
-hMMMMMMMMMMMMMMMMMMMMMh-
.sMMMMMMMMMMMMMMMMMMMMMMs.
:dMMMMMMMMMMMMMMMMMMMMMMd:
+NMMMMMMMMMMMMMMMMMMMMMMN+
-+MMMMMMMMMMMMMMMMMMMMMM+-
-hMMMMMMMMMMMMMMMMMMMMh-
./y:-odNMMMMMNmdo-.:y.
-oyyyyyyyyyyyyo-
`}</pre>
            <div className="font-mono text-[11px] space-y-0.5 flex-1">
              <div className="font-bold text-sgc-bright text-sm mb-1">sg@cube</div>
              <SysInfo label="Assistant" value="SG_CUBE v2.0" />
              <SysInfo label="Model" value="gemini-2.5-flash" />
              <SysInfo label="Vision" value="qwen2.5vl:3b" />
              <SysInfo label="STT" value="faster-whisper" />
              <SysInfo label="TTS" value="piper (ryan-high)" />
              <SysInfo label="Wake" value="onyx (vosk)" />
              <SysInfo label="Memory" value={`${stats.memory_used_gb.toFixed(1)} / ${stats.memory_total_gb.toFixed(1)} GiB`} />
              <SysInfo label="Tools" value={`${totalTools} registered`} />
              <SysInfo label="Agents" value={`${agents.length || 5} · ${summary.thinking} thinking`} />
              <div className="flex gap-1 mt-1.5">
                {BUCKET_ORDER.slice(0, 8).map((b) => {
                  const bucket = buckets.find((x) => x.name === b)
                  return <span key={b} className="w-3 h-3 border border-sgc-border" style={{ background: bucket?.color ?? 'transparent', opacity: bucket ? 0.8 : 0.15 }} />
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Agents monitor */}
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

        {/* Recent activity */}
        <div className="border border-sgc-border bg-sgc-panel relative flex-1 min-h-[100px]">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border">
            <span className="text-sgc-border-bright">sgcube</span>:~$ tail --events 5
          </div>
          <div className="p-3 flex flex-col gap-1">
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

      {/* CENTER: the CUBE, dominant */}
      <div className="flex-1 flex items-center justify-center relative overflow-hidden">
        <svg viewBox="0 0 500 500" className="w-full h-full max-w-[500px] max-h-[500px]" preserveAspectRatio="xMidYMid meet">
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
        <div className="absolute flex flex-col items-center gap-8" style={{ perspective: '1200px' }}>
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
          <div className="flex flex-col items-center gap-1 font-mono text-[9px] tracking-wider text-sgc-dim">
            <div className="uppercase">agents on cube</div>
            <div className="text-sgc-secondary">Cmd · Pln · Grd · Opr · Wch</div>
          </div>
        </div>
      </div>

      {/* RIGHT: sparklines + services grid — matches the reference monitor panel */}
      <div className="w-[280px] flex flex-col gap-3 p-4 overflow-y-auto border-l border-sgc-border">

        {/* System monitor with live sparklines */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border">
            <span className="text-sgc-border-bright">sgcube</span>:~$ monitor
          </div>
          <div className="p-3 flex flex-col gap-2.5">
            <Sparkline label="CPU"  data={cpuHist}  value={stats.cpu_percent}    color="#00e5ff" />
            <Sparkline label="MEM"  data={memHist}  value={stats.memory_percent} color="#00ff41" />
            <Sparkline label="DISK" data={diskHist} value={stats.disk_percent}   color="#ff8800" />
            {stats.temp_c !== null && (
              <div className="flex items-baseline justify-between font-mono text-[10px] tracking-wider pt-0.5">
                <span className="text-sgc-dim">TEMP</span>
                <span className="text-sgc-bright tabular-nums">{stats.temp_c.toFixed(1)}°C</span>
              </div>
            )}
            <div className="flex items-baseline justify-between font-mono text-[10px] tracking-wider">
              <span className="text-sgc-dim">NET</span>
              <div className="flex gap-2 text-sgc-bright">
                <span>↓ {formatBytes(stats.net_down_bps)}</span>
                <span className="text-sgc-dim">·</span>
                <span>↑ {formatBytes(stats.net_up_bps)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Services grid — tools by category */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border flex items-center justify-between">
            <span><span className="text-sgc-border-bright">sgcube</span>:~$ tools</span>
            <span className="text-sgc-dim">{totalTools} total</span>
          </div>
          <div className="p-3 grid grid-cols-2 gap-1.5">
            {buckets.map((b) => (
              <div key={b.name} className="flex items-center gap-1.5 font-mono text-[10px]">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{
                    background: b.used > 0 ? b.color : `${b.color}66`,
                    boxShadow: b.used > 0 ? `0 0 6px ${b.color}` : 'none',
                  }}
                />
                <span className="text-sgc-secondary uppercase tracking-wider flex-1 truncate">{b.name}</span>
                <span className="text-sgc-bright tabular-nums">{b.count}</span>
              </div>
            ))}
            {buckets.length === 0 && (
              <div className="col-span-2 text-sgc-dim italic">Loading tool catalog…</div>
            )}
          </div>
        </div>

        {/* Watcher / background services status */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border">
            <span className="text-sgc-border-bright">sgcube</span>:~$ services
          </div>
          <div className="p-3 grid grid-cols-2 gap-1.5 font-mono text-[10px]">
            {[
              { name: 'WS Bus',    ok: connected },
              { name: 'Telemetry', ok: (systemStats?.cpu_percent ?? 0) > 0 || cpuHist.length > 0 },
              { name: 'Agents',    ok: agents.length > 0 },
              { name: 'Tools',     ok: totalTools > 0 },
            ].map((s) => (
              <div key={s.name} className="flex items-center gap-1.5">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: s.ok ? '#00ff41' : '#ff0033', boxShadow: s.ok ? '0 0 6px #00ff41' : '0 0 6px #ff0033' }}
                />
                <span className="text-sgc-secondary uppercase tracking-wider flex-1 truncate">{s.name}</span>
                <span className={s.ok ? 'text-[#00ff41]' : 'text-sgc-danger'}>{s.ok ? 'OK' : 'DOWN'}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function SysInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="text-sgc-dim shrink-0 w-14">{label}:</span>
      <span className="text-sgc-bright truncate">{value}</span>
    </div>
  )
}
