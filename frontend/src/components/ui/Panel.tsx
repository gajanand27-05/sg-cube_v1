import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface PanelProps {
  /** Terminal-style command shown in the title bar, e.g. "neofetch". */
  cmd?: string
  /** Right-aligned content in the title bar (counts, uptime, etc.). */
  title?: ReactNode
  /** Draw the HUD corner brackets. Default true. */
  brackets?: boolean
  className?: string
  bodyClassName?: string
  children?: ReactNode
}

/**
 * The standard SG_CUBE framed panel: bordered card with optional corner
 * brackets and a `sgcube:~$ <cmd>` title bar. Replaces the hand-rolled
 * duplicate in every Dashboard section (the corner-bracket + title-bar
 * pattern was copy-pasted six times there).
 */
export function Panel({
  cmd,
  title,
  brackets = true,
  className,
  bodyClassName,
  children,
}: PanelProps) {
  return (
    <div className={cn("relative border border-sgc-border bg-sgc-panel", className)}>
      {brackets && (
        <>
          <span className="absolute top-0 left-0 w-3 h-3 border-t border-l border-sgc-border-bright pointer-events-none" />
          <span className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-sgc-border-bright pointer-events-none" />
        </>
      )}
      {cmd && (
        <div className="flex items-center justify-between font-mono text-[11px] text-sgc-secondary px-3 py-1.5 border-b border-sgc-border">
          <span>
            <span className="text-sgc-border-bright">sgcube</span>:~$ {cmd}
          </span>
          {title}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  )
}
