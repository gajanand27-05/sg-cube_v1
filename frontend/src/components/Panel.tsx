import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type StatusTone = "success" | "warning" | "danger" | "cyan" | "muted";

const toneClasses: Record<StatusTone, string> = {
  success: "text-hud-success",
  warning: "text-hud-warning",
  danger: "text-hud-danger",
  cyan: "text-hud-cyan-glow",
  muted: "text-hud-text-dim",
};

interface PanelProps {
  title?: string;
  number?: string;
  status?: string;
  statusTone?: StatusTone;
  action?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
}

export function Panel({
  title,
  number,
  status,
  statusTone = "cyan",
  action,
  className,
  bodyClassName,
  children,
}: PanelProps) {
  return (
    <section className={cn("hud-panel", className)}>
      <Corners />
      {(title || status || action) && (
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-hud-border-dim">
          <div className="flex items-center gap-2 min-w-0">
            {number && (
              <span className="inline-flex items-center justify-center w-6 h-6 rounded-full border border-hud-border text-[10px] font-mono text-hud-cyan-glow shrink-0">
                {number}
              </span>
            )}
            {title && <h2 className="hud-heading truncate">{title}</h2>}
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {status && (
              <span
                className={cn(
                  "text-[10px] uppercase tracking-[0.2em] font-semibold",
                  toneClasses[statusTone],
                )}
              >
                {status}
              </span>
            )}
            {action}
          </div>
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

function Corners() {
  const base = "absolute w-2.5 h-2.5 border-hud-cyan pointer-events-none";
  return (
    <>
      <span className={cn(base, "top-0 left-0 border-t border-l")} />
      <span className={cn(base, "top-0 right-0 border-t border-r")} />
      <span className={cn(base, "bottom-0 left-0 border-b border-l")} />
      <span className={cn(base, "bottom-0 right-0 border-b border-r")} />
    </>
  );
}
