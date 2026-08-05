import { useUiConnectionState, useUiEvent } from "@/hooks/useUiEvents";

/** Voice Module status readout. Shows connection state + wake word status. */
export function VoiceModulePanel() {
  const connection = useUiConnectionState();
  const wakeHeard = useUiEvent("wake_heard");

  const statusText =
    connection === "open" ? "Connected" : connection === "connecting" ? "Connecting..." : "Disconnected";
  const statusColor =
    connection === "open" ? "text-hud-success" : connection === "connecting" ? "text-hud-warning" : "text-hud-danger";

  const wakeStatus = wakeHeard ? "Just received" : "Idle";
  const wakePeak = wakeHeard ? `peak: ${wakeHeard.peak}` : "—";

  return (
    <div className="flex flex-col gap-3 min-h-0 h-full">
      <div className="flex flex-col gap-2">
        <span className="hud-label">Connection</span>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${statusColor}`} style={{
            backgroundColor: "currentColor",
            boxShadow: connection === "open" ? "0 0 8px currentColor" : "none"
          }} />
          <span className="font-mono text-xs text-hud-text">{statusText}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Wake Word</span>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-xs text-hud-text-dim">{wakeStatus}</span>
          <span className="font-mono text-[10px] text-hud-text-dim">{wakePeak}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Input Mode</span>
        <span className="font-mono text-xs text-hud-text">Voice + Local</span>
      </div>
    </div>
  );
}