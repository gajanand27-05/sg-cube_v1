import { useUiEvent } from "@/hooks/useUiEvents";

/** Module Status panel. Shows model, memory status, and system info. */
export function ModuleStatusPanel() {
  const metrics = useUiEvent("ai_metrics");
  const vision = useUiEvent("vision_update");

  const modelName = metrics?.active_model ?? "—";
  const memoryStatus = "Ollama Cloud" ;
  const visionStatus = vision ? "Active" : "Idle";
  const visionApp = vision?.windows?.[0] ?? "—";

  return (
    <div className="flex flex-col gap-4 min-h-0 h-full">
      <div className="flex flex-col gap-2">
        <span className="hud-label">Model</span>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-xs text-hud-text">{modelName}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Memory</span>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-xs text-hud-text">{memoryStatus}</span>
          <span className="font-mono text-[10px] text-hud-text-dim">ChromaDB</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Vision</span>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-xs text-hud-text">{visionStatus}</span>
          {vision && <span className="font-mono text-[10px] text-hud-text-dim">{visionApp}</span>}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">System</span>
        <span className="font-mono text-xs text-hud-text">Local-first</span>
      </div>
    </div>
  );
}