import { SystemStatsPayload } from "@/lib/uiEvents";
import { useUiEvent } from "@/hooks/useUiEvents";
import { Cpu, HardDrive } from "lucide-react";

/** System stats readout. Shows CPU/RAM/Disk from SystemStatsEvent. */
export function SystemStatsPanel() {
  const stats = useUiEvent<SystemStatsEvent>("system_stats");

  const cpu = stats?.cpu_percent ?? null;
  const mem = stats?.memory_percent ?? null;
  const disk = stats?.disk_percent ?? null;

  const barColor = (v: number | null) => {
    if (v === null) return "text-hud-warning";
    return v < 60 ? "text-hud-success" : v < 85 ? "text-hud-warning" : "text-hud-danger";
  };

  const barWidth = (v: number | null) => {
    if (v === null) return "0%";
    return `${Math.min(v, 100)}%`;
  };

  return (
    <div className="flex flex-col gap-4 min-h-0 h-full">
      {/* CPU */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Cpu className="w-3.5 h-3.5 text-hud-text-dim" />
            <span className="hud-label">CPU</span>
          </div>
          <span className={`font-mono text-[10px] ${barColor(cpu)}`}>
            {cpu !== null ? `${Math.round(cpu)}%` : "—"}
          </span>
        </div>
        <div className="h-1.5 rounded-sm bg-bg-overlay/50 overflow-hidden">
          <div
            className={`h-full rounded-sm transition-all duration-500 ${barColor(cpu)}`}
            style={{
              width: barWidth(cpu),
              backgroundColor: "currentColor",
            }}
          />
        </div>
      </div>

      {/* Memory */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MemoryStick className="w-3.5 h-3.5 text-hud-text-dim" />
            <span className="hud-label">RAM</span>
          </div>
          <span className={`font-mono text-[10px] ${barColor(mem)}`}>
            {mem !== null
              ? `${Math.round(mem)}%`
              : "—"}
          </span>
        </div>
        <div className="h-1.5 rounded-sm bg-bg-overlay/50 overflow-hidden">
          <div
            className={`h-full rounded-sm transition-all duration-500 ${barColor(mem)}`}
            style={{
              width: barWidth(mem),
              backgroundColor: "currentColor",
            }}
          />
        </div>
      </div>

      {/* Disk */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <HardDrive className="w-3.5 h-3.5 text-hud-text-dim" />
            <span className="hud-label">Disk</span>
          </div>
          <span className={`font-mono text-[10px] ${barColor(disk)}`}>
            {disk !== null
              ? `${Math.round(disk)}%`
              : "—"}
          </span>
        </div>
        <div className="h-1.5 rounded-sm bg-bg-overlay/50 overflow-hidden">
          <div
            className={`h-full rounded-sm transition-all duration-500 ${barColor(disk)}`}
            style={{
              width: barWidth(disk),
              backgroundColor: "currentColor",
            }}
          />
        </div>
      </div>
    </div>
  );
}