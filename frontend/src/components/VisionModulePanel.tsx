import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { statusPillClass, statusToneClasses } from "@/components/Panel";
import type { DetectedObject } from "@/lib/uiEvents";
import {
  useUiEvent,
  useUiEventEnvelope,
  useUiEventListener,
} from "@/hooks/useUiEvents";
import { Camera, CameraOff, Zap } from "lucide-react";

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

/** Backend HTTP base — same host the WS hook targets, http instead of ws. */
const API_BASE =
  ((import.meta.env.VITE_API_URL as string | undefined) ?? "").length > 0
    ? (import.meta.env.VITE_API_URL as string)
    : "http://127.0.0.1:8001";

const FEED_STALE_MS = 3000;

type PhoneConnect = { url: string | null; reachable_from_lan: boolean };

/** The concrete address the phone should open, straight from the backend —
 *  never a placeholder the user has to transcribe (that shipped once and the
 *  literal "<pc-ip>" ended up typed into a phone). */
function usePhoneConnect(): PhoneConnect | null {
  const [info, setInfo] = useState<PhoneConnect | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/vision/phone_connect`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => alive && d && setInfo(d))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return info;
}

/** QR + copyable URL block shown wherever the phone needs connecting. */
function PhoneConnectHint() {
  const info = usePhoneConnect();
  if (info === null || info.url === null) {
    return (
      <span className="text-[10px] font-mono text-hud-text-dim">
        backend unreachable — start it, then reopen this panel
      </span>
    );
  }
  return (
    <div className="flex items-center gap-3">
      <img
        src={`${API_BASE}/vision/phone_connect_qr.png`}
        alt={`QR code for ${info.url}`}
        className="w-[88px] h-[88px] rounded-sm border border-hud-border-dim bg-white p-0.5 shrink-0"
        onError={(e) => {
          // QR generation unavailable (404) — the URL text still works.
          (e.target as HTMLImageElement).style.display = "none";
        }}
      />
      <div className="flex flex-col gap-1.5 min-w-0">
        <span className="text-[10px] font-mono text-hud-text-dim leading-relaxed">
          Scan with the phone camera (same Wi-Fi), or open:
        </span>
        <code className="text-[10px] font-mono text-hud-cyan-glow border border-hud-border-dim
                         rounded px-1.5 py-1 select-all break-all">
          {info.url}
        </code>
        {!info.reachable_from_lan && (
          <span className="text-[9px] font-mono text-hud-danger leading-relaxed">
            ⚠ backend is bound to localhost — set APP_HOST=0.0.0.0 in .env and restart
          </span>
        )}
      </div>
    </div>
  );
}

const OBSTACLE_TTL_MS = 4000;

/** Latest confirmed YOLO obstacle, overlaid on the feed. Fades out when no
 *  fresh event arrives — a stale obstacle chip is worse than none. */
function ObstacleChip({ now }: { now: number }) {
  const env = useUiEventEnvelope("obstacle");
  if (env === null) return null;
  const ageMs = now - Date.parse(env.timestamp);
  if (!Number.isFinite(ageMs) || ageMs > OBSTACLE_TTL_MS) return null;
  const o = env.payload;
  const arrow = o.direction === "left" ? "←" : o.direction === "right" ? "→" : "↑";
  return (
    <span
      className={cn(
        "absolute bottom-1.5 left-1.5 px-1.5 py-0.5 rounded-sm border font-mono text-[10px]",
        o.priority === "critical"
          ? "border-hud-danger text-hud-danger bg-bg-base/80"
          : "border-hud-warning text-hud-warning bg-bg-base/70",
      )}
    >
      {arrow} {o.label} · {o.clipped ? "very close" : `${o.distance_m.toFixed(1)}m`}
    </span>
  );
}

/** Phone feed overlay zone. Mounts inside VisionModulePanel when enabled.
 *
 *  PhoneFrameEvent carries metadata only; on each new frame_id the <img>
 *  refetches /vision/phone_frame (Cache-Control: no-store on the backend, plus
 *  the frame_id query param as a belt-and-braces cache buster). */
export function PhoneFeedOverlayZone() {
  const [enabled, setEnabled] = useState(false);
  const env = useUiEventEnvelope("phone_frame");
  const frame = env?.payload ?? null;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [enabled]);

  if (!enabled) {
    return (
      <details className="group">
        <summary className="flex items-center justify-between cursor-pointer px-2.5 py-1.5
                             rounded-sm border border-hud-border-dim/60 hover:border-hud-cyan
                             transition-colors bg-bg-panel/30 select-none">
          <div className="flex items-center gap-2">
            <Camera className="w-3.5 h-3.5 text-hud-text-dim" />
            <span className="text-[10px] font-mono text-hud-text">Phone Feed</span>
          </div>
          <Zap className="w-3.5 h-3.5 text-hud-warning" />
        </summary>
        <div className="p-2 flex flex-col gap-2">
          <PhoneConnectHint />
          <button
            onClick={() => setEnabled(true)}
            className="w-full flex items-center justify-center gap-2 px-2 py-1.5 rounded-sm
                       border border-hud-success bg-bg-raised/50 hover:bg-bg-raised
                       transition-colors"
          >
            <Camera className="w-3.5 h-3.5 text-hud-success" />
            <span className="text-[10px] font-mono text-hud-success">Enable Feed</span>
          </button>
        </div>
      </details>
    );
  }

  const ageMs = frame === null ? null : now - frame.timestamp * 1000;
  const live = ageMs !== null && ageMs < FEED_STALE_MS;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="hud-label">Phone Feed</span>
          {frame !== null && (
            <span
              className={cn(
                "text-[9px] font-mono uppercase tracking-[0.12em]",
                live ? "text-hud-success" : "text-hud-warning",
              )}
            >
              {live ? `live · ${frame.fps_received.toFixed(1)} fps · ${frame.mode}` : "stale"}
            </span>
          )}
        </div>
        <button
          onClick={() => setEnabled(false)}
          className="flex items-center gap-1 px-1.5 py-0.5 rounded-sm border border-hud-danger
                     bg-bg-overlay/50 hover:bg-bg-raised transition-colors"
        >
          <CameraOff className="w-3 h-3 text-hud-danger" />
          <span className="text-[9px] font-mono text-hud-danger">Disconnect</span>
        </button>
      </div>

      {frame === null ? (
        <div className="relative w-full rounded-sm border border-dashed border-hud-cyan/30
                        bg-bg-overlay/30 flex flex-col items-center justify-center gap-2 p-3">
          <div className="flex items-center gap-2">
            <Camera className="w-4 h-4 text-hud-cyan/30 animate-pulse" />
            <span className="text-[10px] font-mono text-hud-text-dim">Waiting for frames...</span>
          </div>
          <PhoneConnectHint />
        </div>
      ) : (
        <div className="relative">
          <img
            src={`${API_BASE}/vision/phone_frame?f=${frame.frame_id}`}
            alt={`Phone camera frame ${frame.frame_id} (${frame.mode})`}
            className={cn(
              "w-full rounded-sm border object-contain bg-black",
              live ? "border-hud-cyan/40" : "border-hud-warning/40 opacity-60",
            )}
          />
          <ObstacleChip now={now} />
        </div>
      )}
    </div>
  );
}

const HAPTIC_FLASH_MS = 1500;

/** The backend sends -1 for anything it could not measure, precisely so this
 *  never renders as a real 0. Anything negative or non-finite is "unmeasured"
 *  and comes back as null, which the callers print as an em-dash. */
export function measured(value: number | undefined): number | null {
  if (value === undefined || !Number.isFinite(value) || value < 0) return null;
  return value;
}

function fmt(value: number | null, digits: number, unit = ""): string {
  return value === null ? "—" : `${value.toFixed(digits)}${unit}`;
}

/** Phase 3/4 telemetry: current vision mode, health counters, and a brief
 *  flash when a haptic pulse is sent to the phone.
 *
 *  Hook choice follows T-panel-listener-state-lost-on-remount: mode and health
 *  are standing state, so they use the cache-seeded useUiEvent and survive an
 *  HMR/StrictMode remount. The haptic flash is transient by definition — it
 *  must NOT be replayed from the cache on remount — so it stays a listener. */
function VisionModeHealthRow() {
  const modeEvent = useUiEvent("mode_change");
  const health = useUiEvent("vision_health");
  const [haptic, setHaptic] = useState<{ pulses: number; at: number } | null>(
    null,
  );

  useUiEventListener("haptic", (p) => {
    setHaptic({ pulses: p.pulses, at: Date.now() });
  });

  useEffect(() => {
    if (haptic === null) return;
    const id = setTimeout(() => setHaptic(null), HAPTIC_FLASH_MS);
    return () => clearTimeout(id);
  }, [haptic]);

  // mode_change is the authoritative toggle; vision_health carries the mode too
  // and is the only source if the panel mounted after the last toggle.
  const mode = modeEvent?.mode ?? health?.mode ?? null;

  const fpsIn = fmt(measured(health?.fps_received), 1);
  const fpsOut = fmt(measured(health?.fps_processed), 1);
  const latency = fmt(measured(health?.detector_latency_ms), 0, "ms");
  const dropped = fmt(measured(health?.dropped_frames), 0);
  const queue = fmt(measured(health?.tts_queue_depth), 0);
  // NOT measured(): for this one field a negative value is a real reading — a
  // persistently negative age means the phone-clock offset was estimated with
  // the wrong sign, the one fault vision-health cannot otherwise detect, and
  // measured()'s `< 0` test rendered it as the same em-dash as "handshake not
  // done yet". The backend now states outright whether it measured it; the
  // sign test stays only as the fallback for a backend that doesn't.
  const ageValue = health?.frame_age_ms;
  const ageKnown =
    health?.frame_age_measured ?? (ageValue !== undefined && ageValue >= 0);
  const age =
    ageKnown && Number.isFinite(ageValue) ? fmt(ageValue as number, 0, "ms") : "—";
  // Staleness drops, NOT the fps-throttle drops above — throttling is expected
  // at 2fps, stale frames mean the link is too slow to guide someone safely.
  const stale = fmt(measured(health?.frames_dropped_stale), 0);

  return (
    <div className="flex flex-col gap-1 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="hud-label">Vision mode</span>
        <div className="flex items-center gap-1.5 min-w-0">
          {haptic !== null && (
            <span
              key={haptic.at}
              className="px-1.5 py-0.5 rounded-sm border border-hud-warning text-[9px]
                         uppercase tracking-[0.12em] text-hud-warning font-mono hud-crossfade"
            >
              haptic ×{haptic.pulses}
            </span>
          )}
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-hud-cyan-glow truncate">
            {mode ?? <span className="text-hud-text-dim">—</span>}
          </span>
        </div>
      </div>
      <span
        className="font-mono text-[10px] text-hud-text-dim leading-relaxed"
        title="frames received / processed per second · detector latency · frames dropped by the fps throttle · TTS queue depth · end-to-end frame age · frames dropped for being stale. “—” means the backend could not measure it."
      >
        {fpsIn} / {fpsOut} fps · det {latency} · drop {dropped} · q {queue} · age{" "}
        {age} · stale {stale}
      </span>
      <ReadModeTranscript />
    </div>
  );
}

/** What Read mode actually recognized.
 *
 *  ocr_read was published by the backend and consumed by nobody — the mode's
 *  entire output was spoken and otherwise invisible, while navigate has its
 *  obstacle chips and scan has these health counters. Since the operator
 *  watching this HUD is usually NOT the person wearing the phone, "what did it
 *  read" is the one thing they cannot otherwise observe.
 *
 *  A listener, not useUiEvent: these are a running transcript, and replaying a
 *  cached line on remount would show stale text as if it were just read. Lines
 *  arrive one event each, so the panel keeps the last few. */
const OCR_LINES_SHOWN = 3;

function ReadModeTranscript() {
  const [lines, setLines] = useState<{ text: string; confidence: number; at: number }[]>([]);

  useUiEventListener("ocr_read", (p) => {
    setLines((prev) => [
      ...prev.slice(-(OCR_LINES_SHOWN - 1)),
      { text: p.text, confidence: p.confidence, at: Date.now() },
    ]);
  });

  if (lines.length === 0) return null;
  return (
    <div className="flex flex-col gap-0.5 mt-0.5 min-w-0">
      <span className="hud-label text-[9px]">Read</span>
      {lines.map((line) => (
        <span
          key={line.at}
          className="font-mono text-[10px] text-hud-cyan-glow truncate"
          title={`${line.text} (${Math.round(line.confidence * 100)}% confidence)`}
        >
          {line.text}
        </span>
      ))}
    </div>
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

      {/* Row 5 — Vision mode + health telemetry (Phase 3/4) */}
      <VisionModeHealthRow />

      {/* Row 6 — Phone feed overlay zone (Phase 1) */}
      <PhoneFeedOverlayZone />
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
