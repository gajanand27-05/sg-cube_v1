import { useUiConnectionState, useUiEvent } from "@/hooks/useUiEvents";
import { Cpu, Cloud, Globe, Zap } from "lucide-react";

/** Response Mode panel. Shows current backend routing and capabilities. */
export function ResponseModePanel() {
  const connection = useUiConnectionState();
  const metrics = useUiEvent("ai_metrics");

  const mode = connection === "open" ? "LOCAL-FIRST" : "STANDBY";
  const isOnline = connection === "open";
  const model = metrics?.active_model ?? "—";

  return (
    <div className="flex flex-col gap-4 min-h-0 h-full">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-hud-warning" />
          <span className="font-mono text-[10px] text-hud-warning uppercase">{mode}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Model</span>
        <div className="flex items-center gap-2">
          {isOnline ? (
            <Cpu className="w-3.5 h-3.5 text-hud-success" />
          ) : (
            <Cloud className="w-3.5 h-3.5 text-hud-danger" />
          )}
          <span className="font-mono text-xs text-hud-text truncate">{model}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Capabilities</span>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Globe className="w-3.5 h-3.5 text-hud-success" />
            <span className="font-mono text-[10px] text-hud-text">Vision Scan</span>
          </div>
          <div className="flex items-center gap-2">
            <Cpu className="w-3.5 h-3.5 text-hud-success" />
            <span className="font-mono text-[10px] text-hud-text">Memory LTM</span>
          </div>
        </div>
      </div>
    </div>
  );
}