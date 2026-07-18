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

export function BottomBar() {
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
        <Stat icon={<Cpu className="w-4 h-4" />} label="CPU" value="23%" />
        <Stat icon={<MemoryStick className="w-4 h-4" />} label="RAM" value="61%" />
        <Stat icon={<Gauge className="w-4 h-4" />} label="GPU" value="41%" />
        <Stat icon={<Thermometer className="w-4 h-4" />} label="TEMP" value="48°C" />
        <Stat icon={<Wifi className="w-4 h-4" />} label="NETWORK" value="Local" />
        <Stat icon={<Battery className="w-4 h-4" />} label="BATTERY" value="82%" />
        <Stat icon={<Timer className="w-4 h-4" />} label="LATENCY" value="12ms" tone="cyan" />
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
  return (
    <div className="flex items-center gap-2">
      <span className={cn("text-hud-text-dim", tone === "cyan" && "text-hud-cyan")}>{icon}</span>
      <div className="leading-tight">
        <div className="text-[9px] uppercase tracking-[0.15em] text-hud-text-muted">{label}</div>
        <div
          className={cn(
            "text-xs font-mono",
            tone === "cyan" ? "text-hud-cyan-glow" : "text-hud-text",
          )}
        >
          {value}
        </div>
      </div>
    </div>
  );
}
