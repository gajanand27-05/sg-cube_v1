import { useEffect, useRef, useState } from 'react'
import type { SystemStats } from '@/hooks/useWebSocket'

interface Props {
  systemStats?: SystemStats
}

const CPU_BARS = 24     // number of vertical bars in the load meter
const TEMP_MAX = 95     // scale for the temp dial (°C)

// Small circular gauge — used for temp. Draws a partial arc filled to
// (value / max) with the same tick style as the reference HUD.
function TempDial({ value, max = TEMP_MAX }: { value: number | null; max?: number }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value / max))
  // Arc from 135° to 45° going clockwise (i.e. 270° sweep at bottom).
  const R = 12
  const CX = 14
  const CY = 14
  const startAngle = 135
  const endAngle = startAngle + 270 * pct
  const toXY = (a: number) => [CX + R * Math.cos((a * Math.PI) / 180), CY + R * Math.sin((a * Math.PI) / 180)]
  const [x1, y1] = toXY(startAngle)
  const [x2, y2] = toXY(endAngle)
  const largeArc = 270 * pct > 180 ? 1 : 0
  const arcPath = value == null ? '' : `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`
  const heat = pct > 0.85 ? '#ff0033' : pct > 0.65 ? '#ff8800' : '#00e5ff'
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" className="drop-shadow-[0_0_4px_rgba(0,229,255,0.4)]">
      {/* full backing arc */}
      <path
        d={`M ${toXY(startAngle)[0].toFixed(2)} ${toXY(startAngle)[1].toFixed(2)} A ${R} ${R} 0 1 1 ${toXY(startAngle + 270)[0].toFixed(2)} ${toXY(startAngle + 270)[1].toFixed(2)}`}
        fill="none" stroke="rgba(0,229,255,0.15)" strokeWidth="2" strokeLinecap="round"
      />
      {arcPath && <path d={arcPath} fill="none" stroke={heat} strokeWidth="2" strokeLinecap="round" />}
      <circle cx={CX} cy={CY} r="1.5" fill={heat} />
    </svg>
  )
}

// Analog-style clock face — a nod to the reference's chrome bezel clock.
function ClockFace({ date }: { date: Date }) {
  const h = date.getHours() % 12 + date.getMinutes() / 60
  const m = date.getMinutes() + date.getSeconds() / 60
  const s = date.getSeconds()
  const hourAngle = (h * 30) - 90
  const minAngle = (m * 6) - 90
  const secAngle = (s * 6) - 90
  const R = 11
  const CX = 14
  const CY = 14
  const hand = (angle: number, len: number, w: number, color: string) => {
    const x2 = CX + len * Math.cos((angle * Math.PI) / 180)
    const y2 = CY + len * Math.sin((angle * Math.PI) / 180)
    return <line x1={CX} y1={CY} x2={x2.toFixed(2)} y2={y2.toFixed(2)} stroke={color} strokeWidth={w} strokeLinecap="round" />
  }
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" className="drop-shadow-[0_0_4px_rgba(0,229,255,0.4)]">
      <circle cx={CX} cy={CY} r={R} fill="none" stroke="var(--sgc-dim)" strokeWidth="1" opacity="0.5" />
      <circle cx={CX} cy={CY} r={R + 2} fill="none" stroke="var(--sgc-border-bright)" strokeWidth="0.5" opacity="0.8" strokeDasharray="1 3" />
      {hand(hourAngle, 5.5, 1.4, 'var(--sgc-bright)')}
      {hand(minAngle, 8, 1, 'var(--sgc-border-bright)')}
      {hand(secAngle, 9, 0.5, 'var(--sgc-primary)')}
      <circle cx={CX} cy={CY} r="1.2" fill="var(--sgc-bright)" />
    </svg>
  )
}

export function Footer({ systemStats }: Props) {
  const { temp_c, cpu_percent = 0, memory_percent = 0 } = systemStats || {}
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  // Real CPU history for the load meter. No Math.random(): each bar is
  // an actual sample from telemetry, one bar per 2s tick.
  const [cpuHist, setCpuHist] = useState<number[]>([])
  const lastRef = useRef<SystemStats | null>(null)
  useEffect(() => {
    if (!systemStats || lastRef.current === systemStats) return
    lastRef.current = systemStats
    setCpuHist((prev) => {
      const next = [...prev, systemStats.cpu_percent]
      return next.length > CPU_BARS ? next.slice(next.length - CPU_BARS) : next
    })
  }, [systemStats])

  const clockStr = now.toLocaleTimeString('en-US', { hour12: false })

  return (
    <footer className="flex justify-between items-center h-11 border-t border-sgc-border-bright px-4 bg-[rgba(0,243,255,0.05)] shadow-[0_-2px_10px_rgba(0,243,255,0.1)]">

      {/* Brand */}
      <div className="flex items-center gap-3">
        <div className="w-6 h-6 rounded-full border-2 border-dashed border-sgc-border-bright flex items-center justify-center animate-spin-slow">
          <div className="w-3 h-3 rounded-full bg-sgc-bright shadow-[0_0_10px_#fff]" />
        </div>
        <div>
          <div className="font-sans font-bold text-[13px] text-sgc-bright tracking-wider">SG CUBE v2.0</div>
          <div className="font-mono text-[9px] text-sgc-dim tracking-wider">AGENTIC BUILD</div>
        </div>
      </div>

      {/* System load meters */}
      <div className="flex items-center gap-6">

        {/* CPU load — real history, no jitter */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-sgc-secondary tracking-wider">CPU</span>
          <div className="flex gap-[2px] h-5 items-end w-[76px]">
            {Array.from({ length: CPU_BARS }).map((_, i) => {
              // Right-align history: newest bar on the right.
              const idx = cpuHist.length - CPU_BARS + i
              const v = idx >= 0 ? cpuHist[idx] : 0
              const h = Math.max(6, v)  // minimum 6% so idle bars are still visible
              const warn = v > 85
              const active = v > 0
              return (
                <div
                  key={i}
                  className={`w-[2px] rounded-sm ${!active ? 'bg-sgc-border' : warn ? 'bg-sgc-danger shadow-[0_0_4px_#ff0033]' : 'bg-sgc-border-bright shadow-[0_0_3px_#00e5ff]'}`}
                  style={{ height: `${h}%`, opacity: active ? 0.4 + (v / 200) : 0.3 }}
                />
              )
            })}
          </div>
          <span className="font-mono text-[10px] text-sgc-bright tabular-nums w-9 text-right">
            {cpu_percent.toFixed(0)}%
          </span>
        </div>

        {/* MEM % — smaller, no history */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-sgc-secondary tracking-wider">MEM</span>
          <div className="w-16 h-2 bg-[rgba(0,229,255,0.05)] border border-sgc-border relative overflow-hidden">
            <div
              className={memory_percent > 85 ? 'bg-sgc-danger h-full' : 'bg-sgc-border-bright h-full'}
              style={{ width: `${Math.max(0, Math.min(100, memory_percent))}%`, transition: 'width 400ms' }}
            />
          </div>
          <span className="font-mono text-[10px] text-sgc-bright tabular-nums w-9 text-right">
            {memory_percent.toFixed(0)}%
          </span>
        </div>

        {/* Temp dial */}
        <div className="flex items-center gap-2">
          <TempDial value={temp_c ?? null} />
          <div>
            <div className="font-mono text-[9px] text-sgc-secondary tracking-wider">TEMP</div>
            <div className="font-mono text-[11px] text-sgc-bright tabular-nums">
              {temp_c !== null && temp_c !== undefined ? `${temp_c.toFixed(1)}°C` : 'N/A'}
            </div>
          </div>
        </div>
      </div>

      {/* Clock */}
      <div className="flex items-center gap-2">
        <ClockFace date={now} />
        <div>
          <div className="font-mono text-[9px] text-sgc-secondary tracking-wider">TIME</div>
          <div className="font-mono text-base text-sgc-bright tracking-[2px] tabular-nums">{clockStr}</div>
        </div>
      </div>
    </footer>
  )
}
