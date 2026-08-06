import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";
import type { UiEventType } from "@/lib/uiEvents";
import { useUiEventEnvelope } from "@/hooks/useUiEvents";

/** Full-screen visual map of the SG Cube pipeline.
 *
 *  Static topology (the architecture doesn't change at runtime), live tint:
 *  a node glows while its wire event has fired within ACTIVE_WINDOW_MS, and
 *  stays dimly lit once its event has been seen at all this session — same
 *  semantics as ArchitecturePanel's health dots, per-stage instead of
 *  per-module. Click a node for its role + key files.
 */

const ACTIVE_WINDOW_MS = 4000;

type Group = "input" | "voice" | "route" | "agents" | "memory" | "vision" | "output" | "infra";

const GROUP_COLOR: Record<Group, string> = {
  input: "#7ea3b8",
  voice: "#22d3ee",
  route: "#f59e0b",
  agents: "#67e8f9",
  memory: "#22c55e",
  vision: "#a78bfa",
  output: "#38bdf8",
  infra: "#f472b6",
};

type MapNode = {
  id: string;
  label: string;
  sub: string;
  x: number;
  y: number;
  group: Group;
  /** Wire event that proves this stage ran. Omitted = no live signal exists. */
  event?: UiEventType;
  desc: string;
  files: string[];
};

const W = 128;
const H = 46;

const NODES: MapNode[] = [
  // ── input devices ──
  { id: "mic", label: "Microphone", sub: "sounddevice", x: 30, y: 90, group: "input",
    desc: "Raw audio input. Continuously read by the wake-word listener thread.",
    files: ["backend/daemon/wake_word.py"] },
  { id: "screen", label: "Screen", sub: "capture", x: 30, y: 330, group: "input",
    desc: "Periodic screen capture feeding the passive vision loop (300s interval, skips unchanged screens).",
    files: ["backend/core/vision/capture.py"] },
  { id: "phone", label: "Phone Camera", sub: "WS /ws/phone_stream", x: 30, y: 420, group: "input",
    desc: "VisionClaw phase 1: phone streams camera frames over WebSocket. Frame pixels not yet wired end-to-end.",
    files: ["backend/server/routes/phone_stream.py"] },

  // ── voice path ──
  { id: "wake", label: "Wake Word", sub: "Vosk + VAD", x: 200, y: 90, group: "voice", event: "wake_heard",
    desc: "Detects the wake phrase ('onyx'), captures the utterance with VAD endpointing, handles barge-in and the content-gated follow-up window.",
    files: ["backend/daemon/wake_word.py"] },
  { id: "trigger", label: "Trigger", sub: "voice loop", x: 370, y: 90, group: "voice",
    desc: "Orchestrates a voice turn: chime, transcription, dispatch gates (_is_dispatchable + TTS-echo gate), streaming to TTS, latency marks, dogfooding ledger.",
    files: ["backend/daemon/trigger.py"] },
  { id: "stt", label: "STT", sub: "faster-whisper", x: 540, y: 90, group: "voice", event: "stt_partial",
    desc: "Transcribes captured audio. Silero-VAD filtered, tuned for short English commands; hallucination-prone on near-silence, hence the dispatch gates.",
    files: ["backend/ai_modules/speech/stt_whisper.py"] },

  // ── routing + core ──
  { id: "router", label: "Router", sub: "cache · rules · LLM", x: 710, y: 90, group: "route", event: "intent_resolved",
    desc: "3-tier fast path: normalized cache, regex rule engine (40+ rules, trie-bucketed), then LLM intent layer. Falls through to the agent path.",
    files: ["backend/core/orchestrator/router.py", "backend/core/orchestrator/rule_engine.py"] },
  { id: "brain", label: "Brain", sub: "entry point", x: 880, y: 90, group: "route",
    desc: "Transport-agnostic entry: builds context, runs Commander, buffers prose chunks (never raw tokens) into tts_ready sentences.",
    files: ["backend/core/brain.py"] },
  { id: "commander", label: "Commander", sub: "agent loop ×5", x: 1050, y: 90, group: "agents", event: "token_stream",
    desc: "Central loop, max 5 iterations: Planner → Guardian → Operator, Healer on errors. Adds the current turn to history before snapshotting (turn-stale fix).",
    files: ["backend/core/agents/commander.py"] },

  // ── agent pipeline ──
  { id: "planner", label: "Planner", sub: "LLM → JSON", x: 880, y: 200, group: "agents", event: "agent_reasoning",
    desc: "Streams a JSON envelope of tool calls or final_response from the LLM. FinalResponseExtractor pulls speakable prose out of the token stream.",
    files: ["backend/core/agents/planner.py", "backend/core/agents/prose_stream.py"] },
  { id: "guardian", label: "Guardian", sub: "verifier", x: 1050, y: 200, group: "agents",
    desc: "6-layer safety stack: hallucinated names, schema, injection blacklist, confidence, secondary LLM check, confirmation gate. Fail-closed.",
    files: ["backend/core/agents/guardian.py", "backend/core/agent/verifier.py"] },
  { id: "operator", label: "Operator", sub: "executor", x: 1050, y: 290, group: "agents", event: "tool_started",
    desc: "Executes the verified tool batch through the runtime (timeouts, sandbox guard) and reports tool quality to observability.",
    files: ["backend/core/agents/operator.py", "backend/core/runtime.py"] },
  { id: "tools", label: "Tools", sub: "87 registered", x: 1050, y: 380, group: "agents", event: "tool_finished",
    desc: "Windowing, browser (Playwright), canvas, data sources, files, shell, games… Tier system: readonly / system_write / destructive (default destructive, fail-closed).",
    files: ["backend/core/tools/"] },
  { id: "llm", label: "LLM Provider", sub: "gpt-oss:120b cloud", x: 710, y: 200, group: "route", event: "ai_metrics",
    desc: "Task-routed provider with fallback: Ollama Cloud for reasoning/planning, local Ollama for embeddings and vision.",
    files: ["backend/ai_modules/llm/provider.py", "backend/ai_modules/llm/routing.py"] },

  // ── memory ──
  { id: "memory", label: "Memory", sub: "STM · WM · LTM", x: 540, y: 290, group: "memory", event: "memory_hit",
    desc: "Tiered memory manager. Context assembly for every turn; LTM search is 5-signal scored. Embedding failures raise — zero vectors are refused.",
    files: ["backend/core/memory/manager.py", "backend/core/memory/long_term.py"] },
  { id: "chroma", label: "ChromaDB", sub: "3 collections", x: 540, y: 380, group: "memory",
    desc: "sg_cube_memories (facts), sg_cube_visual (screen observations), sg_cube_timeline (event log). One shared client.",
    files: ["backend/database/"] },

  // ── vision ──
  { id: "visionloop", label: "Vision Loop", sub: "300s tick", x: 200, y: 330, group: "vision", event: "vision_update",
    desc: "Captures the screen, skips if unchanged, sends to the VLM, stores an observation + timeline event.",
    files: ["backend/daemon/vision_loop.py"] },
  { id: "vlm", label: "VLM", sub: "qwen2.5vl", x: 370, y: 330, group: "vision",
    desc: "Local vision-language model describing the screenshot as {app, summary, keywords}.",
    files: ["backend/core/vision/vlm.py"] },
  { id: "ingest", label: "Frame Ingest", sub: "2fps throttle", x: 200, y: 420, group: "vision",
    desc: "Throttles incoming phone frames and publishes PhoneFrameEvent. Obstacle detection (YOLO) lands here in VisionClaw phase 2.",
    files: ["backend/core/vision/frame_ingest.py"] },

  // ── output ──
  { id: "prose", label: "Prose Extract", sub: "state machine", x: 880, y: 470, group: "output",
    desc: "Incrementally pulls the final_response string out of the planner's JSON token stream so TTS never speaks the envelope.",
    files: ["backend/core/agents/prose_stream.py"] },
  { id: "tts", label: "TTS", sub: "Piper · streaming", x: 710, y: 470, group: "output",
    desc: "SentenceQueue serializes sentences into per-call playback sessions (loop-safe). Records spoken text for echo suppression; barge-in stops it.",
    files: ["backend/ai_modules/speech/tts_piper.py", "backend/ai_modules/speech/tts_queue.py"] },
  { id: "speaker", label: "Speaker", sub: "audio out", x: 540, y: 470, group: "input",
    desc: "First audio out is the latency number that matters (wake → first_audio_out).",
    files: ["backend/core/latency.py"] },

  // ── infra ──
  { id: "bus", label: "Event Bus", sub: "async · 3 pools", x: 370, y: 560, group: "infra",
    desc: "Priority event bus (HIGH/NORMAL/LOW workers). Every stage publishes typed events here; it is the single seam between backend and UI.",
    files: ["backend/core/events.py", "backend/daemon/ui_events.py"] },
  { id: "wsui", label: "WS Bridge", sub: "/ws/ui", x: 540, y: 560, group: "infra",
    desc: "Serializes ~27 typed events to JSON envelopes {type, timestamp, payload} and broadcasts to connected HUD clients.",
    files: ["backend/server/ws_ui.py"] },
  { id: "hud", label: "React HUD", sub: "this UI", x: 710, y: 560, group: "infra", event: "system_stats",
    desc: "Panels subscribe via useUiEvent/useUiEventEnvelope (cache-seeded, remount-safe). You are here.",
    files: ["frontend/src/hooks/useUiEvents.ts", "frontend/src/App.tsx"] },
  { id: "telemetry", label: "Telemetry", sub: "2s cadence", x: 200, y: 560, group: "infra", event: "system_stats",
    desc: "CPU / memory / disk / network sampled every 2s and published as SystemStatsEvent.",
    files: ["backend/daemon/telemetry.py"] },
];

/** [from, to] by node id. Rendered as arrows in declaration order. */
const EDGES: Array<[string, string]> = [
  ["mic", "wake"],
  ["wake", "trigger"],
  ["trigger", "stt"],
  ["stt", "router"],
  ["router", "brain"],
  ["brain", "commander"],
  ["commander", "planner"],
  ["planner", "guardian"],
  ["guardian", "operator"],
  ["operator", "tools"],
  ["planner", "llm"],
  ["brain", "memory"],
  ["memory", "chroma"],
  ["screen", "visionloop"],
  ["visionloop", "vlm"],
  ["vlm", "chroma"],
  ["phone", "ingest"],
  ["planner", "prose"],
  ["prose", "tts"],
  ["tts", "speaker"],
  ["telemetry", "bus"],
  ["bus", "wsui"],
  ["wsui", "hud"],
];

const nodeById = new Map(NODES.map((n) => [n.id, n]));

/** Distinct wire events the map listens to, derived from the node list. */
const LIVE_EVENTS = [...new Set(NODES.flatMap((n) => (n.event ? [n.event] : [])))];

function useEventTimestamps(): Map<UiEventType, number> {
  // Hook count is stable: LIVE_EVENTS is module-constant.
  const entries = LIVE_EVENTS.map((type) => {
    const env = useUiEventEnvelope(type);
    return [type, env ? Date.parse(env.timestamp) : NaN] as const;
  });
  return useMemo(
    () => new Map(entries.filter(([, t]) => Number.isFinite(t))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    entries.map(([, t]) => t),
  );
}

export function ArchitectureMapOverlay({ onClose }: { onClose: () => void }) {
  const [selected, setSelected] = useState<MapNode | null>(null);
  const stamps = useEventTimestamps();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const liveness = (n: MapNode): "active" | "seen" | "idle" => {
    if (!n.event) return "idle";
    const t = stamps.get(n.event);
    if (t === undefined) return "idle";
    return now - t < ACTIVE_WINDOW_MS ? "active" : "seen";
  };

  // Portal to body: the opener panel is a click target, so without a portal a
  // click anywhere in the overlay would bubble back up and re-open it. React
  // portals still bubble through the React tree, so stopPropagation too.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col bg-bg-base/95 backdrop-blur-sm"
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
    >
      <div
        className="flex-1 flex flex-col m-4 border border-hud-border bg-bg-panel/80 shadow-hud-glow relative min-h-0"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-3 border-b border-hud-border-dim shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="hud-heading">SG-Cube System Architecture</h2>
            <span className="text-[9px] font-mono text-hud-text-dim uppercase tracking-[0.2em]">
              live map — glowing nodes fired within {ACTIVE_WINDOW_MS / 1000}s
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-sm border border-hud-border-dim hover:border-hud-danger transition-colors"
            aria-label="Close architecture map"
          >
            <X className="w-4 h-4 text-hud-text-dim" />
          </button>
        </header>

        <div className="flex-1 flex min-h-0">
          <svg
            viewBox="0 0 1210 640"
            className="flex-1 min-w-0 h-full"
            preserveAspectRatio="xMidYMid meet"
          >
            <defs>
              <marker
                id="arch-arrow"
                viewBox="0 0 8 8"
                refX="7"
                refY="4"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 8 4 L 0 8 z" fill="rgba(34,211,238,0.5)" />
              </marker>
            </defs>

            {EDGES.map(([fromId, toId]) => {
              const a = nodeById.get(fromId)!;
              const b = nodeById.get(toId)!;
              // Attach to the facing edge midpoints of each box.
              const ax = a.x + W / 2;
              const ay = a.y + H / 2;
              const bx = b.x + W / 2;
              const by = b.y + H / 2;
              const dx = bx - ax;
              const dy = by - ay;
              const horizontal = Math.abs(dx) > Math.abs(dy);
              const x1 = horizontal ? a.x + (dx > 0 ? W : 0) : ax;
              const y1 = horizontal ? ay : a.y + (dy > 0 ? H : 0);
              const x2 = horizontal ? b.x + (dx > 0 ? 0 : W) : bx;
              const y2 = horizontal ? by : b.y + (dy > 0 ? 0 : H);
              return (
                <line
                  key={`${fromId}-${toId}`}
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke="rgba(34,211,238,0.25)"
                  strokeWidth={1.2}
                  markerEnd="url(#arch-arrow)"
                />
              );
            })}

            {NODES.map((n) => {
              const state = liveness(n);
              const color = GROUP_COLOR[n.group];
              const isSelected = selected?.id === n.id;
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x}, ${n.y})`}
                  className="cursor-pointer"
                  onClick={() => setSelected(isSelected ? null : n)}
                >
                  <rect
                    width={W}
                    height={H}
                    rx={3}
                    fill={state === "active" ? "rgba(34,211,238,0.14)" : "#0a1226"}
                    stroke={isSelected ? "#67e8f9" : state === "idle" ? "rgba(34,211,238,0.18)" : color}
                    strokeWidth={isSelected ? 2 : state === "active" ? 1.8 : 1}
                    opacity={state === "idle" ? 0.75 : 1}
                  >
                    {state === "active" && (
                      <animate attributeName="opacity" values="1;0.65;1" dur="1.2s" repeatCount="indefinite" />
                    )}
                  </rect>
                  <text x={10} y={19} fontSize={12} fontFamily="JetBrains Mono, monospace" fill="#e0f2fe">
                    {n.label}
                  </text>
                  <text x={10} y={35} fontSize={9} fontFamily="JetBrains Mono, monospace" fill="#7ea3b8">
                    {n.sub}
                  </text>
                  {n.event && (
                    <circle
                      cx={W - 10}
                      cy={10}
                      r={3}
                      fill={state === "active" ? "#22c55e" : state === "seen" ? "#0891b2" : "#4b6478"}
                    />
                  )}
                </g>
              );
            })}
          </svg>

          {/* Detail card */}
          <aside className="w-[300px] shrink-0 border-l border-hud-border-dim p-4 flex flex-col gap-3 overflow-y-auto">
            {selected === null ? (
              <>
                <span className="hud-label">Legend</span>
                {(Object.keys(GROUP_COLOR) as Group[]).map((g) => (
                  <div key={g} className="flex items-center gap-2">
                    <span
                      className="w-3 h-3 rounded-sm border"
                      style={{ borderColor: GROUP_COLOR[g] }}
                    />
                    <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-hud-text-dim">
                      {g}
                    </span>
                  </div>
                ))}
                <p className="font-mono text-[10px] text-hud-text-dim leading-relaxed mt-2">
                  Click a node for its role and source files. The corner dot
                  shows its wire event: green = fired in the last{" "}
                  {ACTIVE_WINDOW_MS / 1000}s, blue = seen this session, grey =
                  not yet.
                </p>
              </>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm text-hud-cyan-glow">{selected.label}</span>
                  <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-hud-text-dim">
                    {selected.group}
                  </span>
                </div>
                <p className="font-mono text-[10px] text-hud-text leading-relaxed">
                  {selected.desc}
                </p>
                <span className="hud-label mt-1">Files</span>
                <div className="flex flex-col gap-1">
                  {selected.files.map((f) => (
                    <code
                      key={f}
                      className="text-[9px] font-mono text-hud-text-dim border border-hud-border-dim rounded-sm px-1.5 py-1 break-all"
                    >
                      {f}
                    </code>
                  ))}
                </div>
                {selected.event && (
                  <>
                    <span className="hud-label mt-1">Wire event</span>
                    <span
                      className={cn(
                        "font-mono text-[10px]",
                        liveness(selected) === "active"
                          ? "text-hud-success"
                          : liveness(selected) === "seen"
                            ? "text-hud-cyan-dim"
                            : "text-hud-text-dim",
                      )}
                    >
                      {selected.event} — {liveness(selected)}
                    </span>
                  </>
                )}
              </>
            )}
          </aside>
        </div>
      </div>
    </div>,
    document.body,
  );
}
