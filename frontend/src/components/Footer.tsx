import { useState, useEffect } from 'react'
import type { SystemStats } from '@/hooks/useWebSocket'

interface Props {
  systemStats?: SystemStats
}

export function Footer({ systemStats }: Props) {
  const { temp_c, cpu_percent = 0 } = systemStats || {};
  const [time, setTime] = useState(new Date().toLocaleTimeString());

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <footer className="flex justify-between items-center h-10 border-t border-sgc-border-bright px-4 bg-[rgba(0,243,255,0.05)] shadow-[0_-2px_10px_rgba(0,243,255,0.1)]">
      <div className="flex items-center gap-4">
        <div className="w-6 h-6 rounded-full border-2 border-dashed border-sgc-border-bright flex items-center justify-center animate-spin-slow">
          <div className="w-3 h-3 rounded-full bg-sgc-bright shadow-[0_0_10px_#fff]" />
        </div>
        <div>
          <div className="font-sans font-bold text-[13px] text-sgc-bright tracking-wider">SG CUBE v2.0</div>
          <div className="font-mono text-[9px] text-sgc-dim tracking-wider">AGENTIC BUILD</div>
        </div>
      </div>

      <div className="flex items-center gap-8">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-sgc-secondary">CPU LOAD</span>
          <div className="flex gap-[2px] h-4 items-end">
            {Array.from({ length: 20 }).map((_, i) => {
              const activeThreshold = (cpu_percent / 100) * 20;
              const jitter = (Math.random() - 0.5) * 4;
              const isActive = i < (activeThreshold + jitter);
              const isWarn = i > 14 && isActive;
              return (
                <div
                  key={i}
                  className={`w-[4px] rounded-sm ${isActive ? (isWarn ? 'bg-sgc-warn' : 'bg-sgc-border-bright shadow-[0_0_4px_#00f3ff]') : 'bg-sgc-border'}`}
                  style={{ height: `${20 + Math.random() * 80}%` }}
                />
              );
            })}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-[18px] h-[18px] rounded-full border-2 border-dashed border-sgc-border-bright flex items-center justify-center">
            <div className="w-3 h-3 rounded-full bg-sgc-bright shadow-[0_0_10px_#fff]" />
          </div>
          <div>
            <div className="font-mono text-[10px] text-sgc-secondary">TEMP</div>
            <div className="font-mono text-xs text-sgc-bright">{temp_c !== null ? `${temp_c}°C` : 'N/A'}</div>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" width="24" height="24" className="drop-shadow-[0_0_5px_#00f3ff]">
          <circle cx="12" cy="12" r="10" fill="none" stroke="var(--sgc-dim)" strokeWidth="2" />
          <path d="M12 6v6l4 2" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="2" />
        </svg>
        <div>
          <div className="font-mono text-[10px] text-sgc-secondary">TIME</div>
          <div className="font-mono text-base text-sgc-bright tracking-[2px]">{time}</div>
        </div>
      </div>
    </footer>
  );
}
