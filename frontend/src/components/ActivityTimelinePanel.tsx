import { useEffect, useRef, useState } from "react";
import { useUiEventListener } from "@/hooks/useUiEvents";
import { cn } from "@/lib/cn";

const MAX_ROWS = 8;

function doneStatus(s: string): ToolRow["status"] {
  return s === "success" ? "success" : "error";
}

type ToolRow = {
  id: number;
  tool: string;
  startedAt: number;
  status: "running" | "success" | "error";
  latencyMs: number | null;
  error: string | null;
};

/** Tool-call timeline. NOT built on AgentToolCallEvent — that event has no
 *  publisher (registry.py:30 subscribes it, nothing constructs it); the
 *  handoff's trap. Use ToolStartedEvent/ToolFinishedEvent, paired by name.
 *
 *  ponytail: pairing is by tool_name only, so two overlapping calls of the
 *  same tool could merge into one row. The turn runtime executes tool calls
 *  sequentially, so today it can't happen. If it ever can, add a request_id
 *  to ToolStartedEvent/ToolFinishedEvent and pair on that.
 */
export function ActivityTimelinePanel() {
  const [rows, setRows] = useState<ToolRow[]>([]);
  const nextId = useRef(0);
  const lastActive = useRef<number | null>(null);

  useUiEventListener("tool_started", (p) => {
    lastActive.current = Date.now();
    const row: ToolRow = {
      id: nextId.current++,
      tool: p.tool_name,
      startedAt: Date.now(),
      status: "running",
      latencyMs: null,
      error: null,
    };
    setRows((r) => [row, ...r].slice(0, MAX_ROWS));
  });

  useUiEventListener("tool_finished", (p) => {
    lastActive.current = Date.now();
    setRows((r) => {
      const idx = r.findIndex((row) => row.tool === p.tool_name && row.status === "running");
      if (idx === -1) {
        const row: ToolRow = {
          id: nextId.current++,
          tool: p.tool_name,
          startedAt: Date.now(),
          status: doneStatus(p.status),
          latencyMs: typeof p.latency_ms === "number" ? p.latency_ms : null,
          error: p.error ?? null,
        };
        return [row, ...r].slice(0, MAX_ROWS);
      }
      const next = [...r];
      next[idx] = {
        ...next[idx],
        status: doneStatus(p.status),
        latencyMs: typeof p.latency_ms === "number" ? p.latency_ms : null,
        error: p.error ?? null,
      };
      return next;
    });
  });

  useEffect(() => {
    const id = setInterval(() => {
      if (lastActive.current !== null && Date.now() - lastActive.current > 60_000) {
        setRows([]);
        lastActive.current = null;
      }
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex flex-col gap-1 min-h-0 h-full">
      <div className="flex-1 min-h-0 overflow-y-auto pr-1 flex flex-col gap-1">
        {rows.length === 0 ? (
          <span className="font-mono text-[10px] text-hud-text-dim">
            no tool activity yet
          </span>
        ) : (
          rows.map((row) => (
            <div
              key={row.id}
              className="flex items-center gap-2 min-w-0 font-mono text-[10px] leading-tight"
            >
              <span
                className={cn(
                  "shrink-0",
                  row.status === "success" && "text-hud-success",
                  row.status === "error" && "text-hud-danger",
                  row.status === "running" && "text-hud-cyan-glow animate-pulse",
                )}
              >
                {row.status === "running" ? "▸" : row.status === "success" ? "✓" : "✗"}
              </span>
              <span className="truncate text-hud-text" title={row.tool}>
                {row.tool}
              </span>
              <span className="ml-auto shrink-0 text-hud-text-dim">
                {row.status === "running"
                  ? "…"
                  : row.latencyMs === null
                    ? "done"
                    : `${row.latencyMs} ms`}
              </span>
              {row.status === "error" && row.error && (
                <span className="shrink-0 text-hud-danger truncate max-w-[40%]" title={row.error}>
                  {row.error}
                </span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
