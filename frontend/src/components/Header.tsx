import { useEffect, useState } from "react";
import { Clock, Activity } from "lucide-react";

export function Header() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const date = now.toLocaleDateString([], { day: "2-digit", month: "2-digit", year: "numeric" });

  return (
    <header className="relative flex items-center justify-between px-6 py-3 border-b border-hud-border-dim bg-bg-panel/60">
      <div className="flex items-center gap-3 w-[340px]">
        <div className="w-10 h-10 rounded-sm border border-hud-cyan bg-bg-raised flex items-center justify-center font-display font-bold text-hud-cyan-glow">
          SG
        </div>
        <div>
          <div className="font-display font-bold tracking-wider text-hud-cyan-glow leading-tight">
            SG CUBE
          </div>
          <div className="text-[10px] uppercase tracking-[0.25em] text-hud-text-dim">
            Your AI Assistant
          </div>
        </div>
      </div>

      <div className="flex-1 text-center font-hud font-semibold tracking-[0.35em] text-sm text-hud-cyan-glow">
        VOICE FIRST. VISION NEXT. INDEPENDENCE ALWAYS.
      </div>

      <div className="flex items-center gap-6 w-[340px] justify-end">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-hud-cyan" />
          <div className="text-right leading-tight">
            <div className="font-mono text-sm text-hud-text">{time}</div>
            <div className="text-[10px] text-hud-text-dim">{date}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-hud-success animate-pulse-glow" />
          <div className="text-right leading-tight">
            <div className="text-xs font-semibold text-hud-success uppercase tracking-wider">
              System Online
            </div>
            <div className="text-[10px] text-hud-text-dim">All systems operational</div>
          </div>
        </div>
        <MiniChart />
      </div>
    </header>
  );
}

function MiniChart() {
  const points = "0,14 8,10 16,12 24,6 32,9 40,4 48,7 56,2 64,5";
  return (
    <svg width="72" height="18" viewBox="0 0 72 18" className="text-hud-cyan opacity-80">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}
