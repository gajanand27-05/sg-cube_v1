import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { statusPillClass, statusToneClasses } from "@/components/Panel";
import type { DetectedObject } from "@/lib/uiEvents";
import { useUiEventEnvelope } from "@/hooks/useUiEvents";

type StatusTone = "success" | "warning" | "danger" | "cyan" | "muted";
type VisionStatus = { status: string; tone: StatusTone };

// Generous by design: the vision loop defaults to a 300s interval and skips
// the VLM entirely while the screen hash is unchanged (vision_loop.py:71-73),
// so a quiet desktop emits NO event for hours. A 10-minute threshold would
// keep the pill permanently stale on every calm session. 30 min is a floor,
// not a guarantee — if the loop dies, the next screen change still fires an
// event, so Stale means "nothing observed for half an hour", not "dead".
const STALE_AFTER_MS = 30 * 60 * 1000;
const MAX_OBJECT_CHIPS = 6;

export function useVisionStatus(): VisionStatus {
  const env = useUiEventEnvelope("vision_update");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return useMemo<VisionStatus>(() => {
    if (env === null) return { status: "Standby", tone: "cyan" };
    const seenAt = Date.parse(env.timestamp);
    if (Number.isNaN(seenAt)) return { status: "Stale", tone: "warning" };
    return now - seenAt < STALE_AFTER_MS
      ? { status: "Live", tone: "success" }
      : { status: "Stale", tone: "warning" };
  }, [env, now]);
}

/** Header pill for the Vision Module panel.
 *
 *  Owns its own 1s ticker, same reason AICoreStatusPill and
 *  MemoryEngineStatusPill do: lifted to App it would re-render the PCB
 *  backdrop and the r3f Canvas once a second. */
export function VisionStatusPill() {
  const { status, tone } = useVisionStatus();
  return (
    <span className={cn(statusPillClass, statusToneClasses[tone])}>{status}</span>
  );
}

export function VisionModulePanel() {
  const env = useUiEventEnvelope("vision_update");
  const payload = env?.payload ?? null;

  // windows is a single-element list carrying the VLM's guess of the active
  // app, not a window list — render windows[0] or nothing (vision_loop.py:100).
  const activeApp =
    payload === null || !Array.isArray(payload.windows) || payload.windows.length === 0
      ? null
      : payload.windows[0];

  const objects: DetectedObject[] = Array.isArray(payload?.objects)
    ? payload.objects
    : [];
  const shownObjects = objects.slice(0, MAX_OBJECT_CHIPS);
  const hiddenObjects = objects.length - shownObjects.length;

  const seenAt =
    env === null ? null : parseSeenAt(env.timestamp);
  const ocrCount = payload === null || !Array.isArray(payload.ocr) ? null : payload.ocr.length;

  return (
    <div className="flex flex-col gap-4">
      {/* Row 1 — Last observation, the VLM's own words */}
      <div className="flex flex-col gap-1 min-w-0">
        <span className="hud-label">Last observation</span>
        {payload === null || !payload.description ? (
          <span className="font-mono text-[10px] text-hud-text-dim">
            awaiting observation
          </span>
        ) : (
          <span
            className="font-mono text-[10px] text-hud-text leading-relaxed line-clamp-3"
            title={payload.description}
          >
            {payload.description}
          </span>
        )}
      </div>

      {/* Row 2 — Seen at + active app */}
      <div className="grid grid-cols-2 gap-3">
        <MetricStat label="Seen at" value={seenAt} />
        <MetricStat label="Active app" value={activeApp} tone="cyan" />
      </div>

      {/* Row 3 — Detected objects as chips */}
      <div className="flex flex-col gap-1 min-w-0">
        <span className="hud-label">Objects</span>
        {shownObjects.length === 0 ? (
          <span className="font-mono text-[10px] text-hud-text-dim">—</span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {shownObjects.map((obj) => (
              <span
                key={obj.label}
                className="px-1.5 py-0.5 rounded-sm border border-hud-border-dim text-[9px] uppercase tracking-[0.12em] text-hud-text-dim font-mono"
                title={obj.label}
              >
                {obj.label}
              </span>
            ))}
            {hiddenObjects > 0 && (
              <span className="px-1.5 py-0.5 rounded-sm text-[9px] uppercase tracking-[0.12em] text-hud-text-muted font-mono">
                +{hiddenObjects} more
              </span>
            )}
          </div>
        )}
      </div>

      {/* Row 4 — OCR count only; the text itself is noise */}
      <div className="flex items-center justify-between gap-3">
        <span className="hud-label">OCR lines</span>
        <span className="font-mono text-xs text-hud-text">
          {ocrCount === null ? (
            <span className="text-hud-text-dim">—</span>
          ) : (
            <span key={ocrCount} className="inline-block hud-crossfade">
              {ocrCount}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

function parseSeenAt(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleTimeString();
}

function MetricStat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | null;
  tone?: "default" | "cyan";
}) {
  return (
    <div className="leading-tight min-w-0">
      <div className="text-[10px] uppercase tracking-[0.15em] text-hud-text-dim">
        {label}
      </div>
      <div
        className={cn(
          "text-sm font-mono truncate",
          tone === "cyan" ? "text-hud-cyan-glow" : "text-hud-text",
        )}
        title={value ?? ""}
      >
        {value === null ? (
          <span className="text-hud-text-dim">—</span>
        ) : (
          <span key={value} className="inline-block hud-crossfade">
            {value}
          </span>
        )}
      </div>
    </div>
  );
}
