import type { AssistantStatus, SystemStats } from '@/hooks/useWebSocket'

interface Props {
  status: AssistantStatus
  systemStats?: SystemStats
}

export function Dashboard({ systemStats }: Props) {
  return (
    <div className="h-full flex overflow-hidden">
      {/* Left column: neofetch + status */}
      <div className="flex-1 flex flex-col gap-4 p-4 overflow-y-auto">
        {/* neofetch card */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border">
            <span className="text-sgc-border-bright">devuser@sgcube</span>:~$ neofetch
          </div>
          <div className="flex gap-4 p-3">
            <pre className="text-sgc-dim text-[10px] leading-tight font-mono">{`
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
      -/++++++++/-
        .:+oooo+:.
            `}</pre>
            <div className="font-mono text-[11px] space-y-0.5">
              <div className="font-bold text-sgc-bright text-sm">devuser@sgcube</div>
              <SysInfo label="OS" value="SG Cube OS 2.0 x86_64" />
              <SysInfo label="Host" value="SG-CUBE v2" />
              <SysInfo label="Kernel" value="6.6.0-sgcube" />
              <SysInfo label="Uptime" value="2 hours, 47 mins" />
              <SysInfo label="Packages" value="1542 (sg-pkg)" />
              <SysInfo label="Shell" value="bash 5.2.21" />
              <SysInfo label="Resolution" value="1920x1080" />
              <SysInfo label="DE" value="SGCube Terminal" />
              <SysInfo label="WM" value="SGWM" />
              <SysInfo label="Theme" value="SG-Dark [GTK3]" />
              <SysInfo label="Icons" value="SGCube-Icons [GTK3]" />
              <SysInfo label="Terminal" value="sgcube-terminal" />
              <SysInfo label="CPU" value="Intel i7-12700K (20) @ 5.00GHz" />
              <SysInfo label="GPU" value="NVIDIA GeForce RTX 3080" />
              <SysInfo label="Memory" value={`${systemStats?.memory_used_gb || '0'}GiB / ${systemStats?.memory_total_gb || '0'}GiB`} />
              <div className="flex gap-1 mt-1">
                {['bg-sgc-bg', 'bg-sgc-danger', 'bg-[#00ff41]', 'bg-sgc-warn', 'bg-blue-500', 'bg-fuchsia-500', 'bg-sgc-primary', 'bg-white'].map((c) => (
                  <span key={c} className={`w-3 h-3 ${c} border border-sgc-border`} />
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Status card */}
        <div className="border border-sgc-border bg-sgc-panel relative">
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright" />
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border">
            <span className="text-sgc-border-bright">devuser@sgcube</span>:~$ sgcube status
          </div>
          <div className="flex justify-between p-3 font-mono text-[11px]">
            <div className="space-y-1">
              <div><span className="text-sgc-dim">ENVIRONMENT</span> <span className="text-sgc-bright">PRODUCTION</span></div>
              <div><span className="text-sgc-dim">VERSION</span> <span className="text-sgc-bright">v2.0.0</span></div>
              <div><span className="text-sgc-dim">UPTIME</span> <span className="text-sgc-bright">2h 47m 13s</span></div>
              <div><span className="text-sgc-dim">LAST DEPLOY</span> <span className="text-sgc-bright">2024-05-23 14:35:10</span></div>
            </div>
            <div className="space-y-1 text-right">
              <div><span className="text-sgc-dim">⛁</span> Database <span className="text-[#00ff41]">[ OK ]</span></div>
              <div><span className="text-sgc-dim">⚡</span> API Gateway <span className="text-[#00ff41]">[ OK ]</span></div>
              <div><span className="text-sgc-dim">🛡</span> Auth Service <span className="text-[#00ff41]">[ OK ]</span></div>
              <div><span className="text-sgc-dim">📁</span> Storage <span className="text-[#00ff41]">[ OK ]</span></div>
              <div><span className="text-sgc-dim">⛭</span> Cache <span className="text-[#00ff41]">[ OK ]</span></div>
            </div>
          </div>
          <div className="font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-t border-sgc-border">
            <span className="text-sgc-border-bright">devuser@sgcube</span>:~$ <span className="animate-blink">█</span>
          </div>
        </div>
      </div>

      {/* Right: HUD rings + cube */}
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
        <div className="absolute" style={{ perspective: '1200px' }}>
          <div className="cube-container">
            <div className="cube">
               <div className="face front">SG</div>
               <div className="face back">SG</div>
               <div className="face right">CUBE</div>
               <div className="face left">CUBE</div>
               <div className="face top"></div>
               <div className="face bottom"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function SysInfo({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-sgc-dim">{label}:</span>{' '}
      <span className="text-sgc-bright">{value}</span>
    </div>
  )
}
