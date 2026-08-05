import { useUiConnectionState, useUiEvent } from "@/hooks/useUiEvents";
import { Layers, Brain, Database, Eye, Mic } from "lucide-react";

/** Architecture overview panel. Shows module health and connections. */
export function ArchitecturePanel() {
  const connection = useUiConnectionState();
  const metrics = useUiEvent("ai_metrics");
  const memory = useUiEvent("memory_hit");
  const vision = useUiEvent("vision_update");

  const modules = [
    { name: "Voice", icon: Mic, status: connection === "open", label: "Wake + STT" },
    { name: "AI Core", icon: Brain, status: metrics !== null, label: "Ollama Cloud" },
    { name: "Memory", icon: Database, status: memory !== null, label: "ChromaDB" },
    { name: "Vision", icon: Eye, status: vision !== null, label: "Screen + VLM" },
    { name: "Tools", icon: Layers, status: true, label: "87 available" },
  ];

  const active = modules.filter(m => m.status).length;

  return (
    <div className="flex flex-col gap-4 min-h-0 h-full">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${metrics ? "bg-hud-success" : "bg-hud-danger"}`}
            style={{ backgroundColor: "currentColor" }} />
          <span className="font-mono text-xs text-hud-text">
            {active}/{modules.length} active
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {modules.map((module) => {
          const Icon = module.icon;
          return (
            <div key={module.name} className="flex items-center gap-2">
              <div className={`p-1 rounded-sm ${
                module.status ? "border border-hud-success bg-bg-raised" : "border border-hud-text-dim"
              }`}>
                <Icon className="w-3 h-3 text-hud-text" />
              </div>
              <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                <span className="font-mono text-[10px] text-hud-text truncate">{module.name}</span>
                <span className="font-mono text-[9px] text-hud-text-dim truncate">{module.label}</span>
              </div>
              <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                module.status ? "bg-hud-success" : "bg-hud-text-dim"
              }`}>
                <div className={module.status ? "animate-pulse" : ""} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}