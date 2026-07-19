import type { ReactNode } from "react";
import {
  Zap,
  Calculator,
  Camera,
  ScanLine,
  FileText,
  Plus,
  Cpu,
  MemoryStick,
  Gauge,
  Thermometer,
  Wifi,
  Battery,
  Timer,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useUiConnectionState, useUiEvent } from "@/hooks/useUiEvents";

const EM_DASH = "—";

function formatBps(bps: number): string {
  if (bps < 1024) return `${Math.round(bps)} B/s`;
  const kb = bps / 1024;
  if (kb < 1024) return `${trim1(kb)} KB/s`;
  const mb = kb / 1024;
  return `${trim1(mb)} MB/s`;
}

function trim1(n: number): string {
  const r = n.toFixed(1);
  return r.endsWith(".0") ? r.slice(0, -2) : r;
}

export function BottomBar() {
  const stats = useUiEvent("system_stats");
  const metrics = useUiEvent("ai_metrics");
  const wsOpen = useUiConnectionState() === "open";
  const live = wsOpen && stats !== null;

  const cpu = live ? `${stats.cpu_percent.toFixed(1)}%` : EM_DASH;
  const ram = live ? `${stats.memory_percent.toFixed(1)}%` : EM_DASH;
  // TODO: no gpu_percent in SystemStatsEvent yet — wire once backend adds it.
  const gpu = EM_DASH;
  const temp =
    live && stats.temp_c !== null ? `${stats.temp_c.toFixed(0)}°C` : EM_DASH;
  const network = live ? formatBps(stats.net_down_bps) : EM_DASH;
  // TODO: no battery_percent in SystemStatsEvent yet — wire once backend adds it.
  const battery = EM_DASH;
  const latency =
    wsOpen && metrics !== null ? `${metrics.latency_ms}ms` : EM_DASH;

  return (
    <footer className="relative flex items-center gap-3 px-4 py-3 border-t border-hud-border-dim bg-bg-panel/60">
      <button className="flex items-center gap-2 px-4 py-2 rounded-sm border border-hud-cyan text-hud-cyan-glow text-xs uppercase tracking-wider font-semibold hover:bg-hud-cyan/10 transition-colors">
        <Zap className="w-4 h-4" />
        Quick Command
      </button>

      <div className="flex items-center gap-2">
        <ActionBtn icon={<Calculator className="w-3.5 h-3.5" />} label="Open Calculator" />
        <ActionBtn icon={<Camera className="w-3.5 h-3.5" />} label="Take Screenshot" />
        <ActionBtn icon={<ScanLine className="w-3.5 h-3.5" />} label="Read Screen" />
        <ActionBtn icon={<FileText className="w-3.5 h-3.5" />} label="Open Notepad" />
        <ActionBtn icon={<Plus className="w-3.5 h-3.5" />} label="Add Command" />
      </div>

      <div className="ml-auto flex items-center gap-5">
        <Stat icon={<Cpu className="w-4 h-4" />} label="CPU" value={cpu} />
        <Stat icon={<MemoryStick className="w-4 h-4" />} label="RAM" value={ram} />
        <Stat icon={<Gauge className="w-4 h-4" />} label="GPU" value={gpu} />
        <Stat icon={<Thermometer className="w-4 h-4" />} label="TEMP" value={temp} />
        <Stat icon={<Wifi className="w-4 h-4" />} label="NETWORK" value={network} />
        <Stat icon={<Battery className="w-4 h-4" />} label="BATTERY" value={battery} />
        <Stat icon={<Timer className="w-4 h-4" />} label="LATENCY" value={latency} tone="cyan" />
      </div>
    </footer>
  );
}

function ActionBtn({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-hud-border-dim text-hud-text-dim text-[11px] hover:border-hud-border hover:text-hud-text transition-colors">
      {icon}
      {label}
    </button>
  );
}

function Stat({
  icon,
  label,
  value,
  tone = "default",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: "default" | "cyan";
}) {
  const empty = value === EM_DASH;
  return (
    <div className="flex items-center gap-2">
      <span className={cn("text-hud-text-dim", tone === "cyan" && "text-hud-cyan")}>{icon}</span>
      <div className="leading-tight">
        <div className="text-[9px] uppercase tracking-[0.15em] text-hud-text-muted">{label}</div>
        <div
          key={value}
          className={cn(
            "text-xs font-mono hud-crossfade",
            empty
              ? "text-hud-text-dim"
              : tone === "cyan"
              ? "text-hud-cyan-glow"
              : "text-hud-text",
          )}
        >
          {value}
        </div>
      </div>
    </div>
  );
}
