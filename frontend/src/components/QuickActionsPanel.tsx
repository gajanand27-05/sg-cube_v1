import { useState } from "react";
import { Search, FileText, FolderOpen, Calculator, MessageSquare, Eye } from "lucide-react";

/** Quick Actions panel. Provides shortcut buttons for common queries. */
export function QuickActionsPanel() {
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [actionTime, setActionTime] = useState<number | null>(null);

  const QUICK_ACTIONS = [
    { id: "search", label: "Web Search", icon: Search, query: "search " },
    { id: "read", label: "Screen Read", icon: Eye, query: "what do you see?" },
    { id: "open", label: "Open App", icon: FolderOpen, query: "open " },
    { id: "calc", label: "Calculator", icon: Calculator, query: "calculate " },
    { id: "note", label: "Take Note", icon: FileText, query: "take note " },
    { id: "chat", label: "Chat", icon: MessageSquare, query: "" },
  ];

  const handleAction = (id: string) => {
    setLastAction(id);
    setActionTime(Date.now());

    // In a real implementation, this would send to backend via WebSocket
    // For now, show the action was clicked
    setTimeout(() => setLastAction(null), 1000);
  };

  const formatTime = () => {
    if (!actionTime) return null;
    const seconds = Math.floor((Date.now() - actionTime) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    return `${Math.floor(seconds / 60)}m ago`;
  };

  return (
    <div className="flex flex-col gap-3 min-h-0 h-full">
      <div className="grid grid-cols-2 gap-2">
        {QUICK_ACTIONS.map((action) => {
          const Icon = action.icon;
          const isActive = lastAction === action.id;
          return (
            <button
              key={action.id}
              onClick={() => handleAction(action.id)}
              className="flex items-center gap-2 px-2 py-1.5 rounded-sm border border-hud-border-dim 
                         hover:border-hud-cyan transition-colors bg-bg-panel/30 hover:bg-bg-raised/50"
            >
              <Icon className="w-3.5 h-3.5 text-hud-text-dim" />
              <span className="text-[10px] font-mono text-hud-text truncate">{action.label}</span>
              {isActive && (
                <span className="w-1.5 h-1.5 rounded-full bg-hud-cyan ml-auto animate-pulse" />
              )}
            </button>
          );
        })}
      </div>

      {lastAction && actionTime && (
        <div className="text-[10px] font-mono text-hud-text-dim text-center pt-1">
          {formatTime()}
        </div>
      )}
    </div>
  );
}