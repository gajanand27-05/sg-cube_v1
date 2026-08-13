export type UiEventEnvelope<T extends UiEventType = UiEventType> = {
  type: T;
  timestamp: string;
  payload: UiEventPayloadMap[T];
};

export type AIMetricsPayload = {
  tokens_per_second: number;
  latency_ms: number;
  inference_ms: number;
  queue_depth: number;
  tool_calls: number;
  active_model: string;
};

export type IntentResolvedPayload = {
  action: string;
  target: string;
  source_layer: "cache" | "rule" | "llm";
};

export type AgentName = "commander" | "planner" | "guardian" | "operator" | "watcher";

export type AgentThinkingPayload = {
  agent_name: AgentName | string;
  is_thinking: boolean;
};

export type AgentReasoningPayload = {
  agent_name: AgentName | string;
  reasoning: string;
};

export type AgentCompletedPayload = {
  agent_name: AgentName | string;
  status: "completed" | "failed" | "verified";
  confidence: number;
  latency_ms: number;
  summary: string | null;
};

export type ProviderDegradedPayload = {
  backend: string;
  reason: string;
  action: "retry" | "fallback" | "gave_up";
  fallback: string;
};

export type MemoryHit = {
  title: string;
  score: number; // 0..1 combined relevance
  source: string;
};

export type MemoryHitPayload = {
  query: string;
  source: string;
  results_count: number;
  /** Null when the publisher had no rich results to attach. */
  hits: MemoryHit[] | null;
  collection: string;
  total_entries: number | null;
};

export type MemoryWriteFailedPayload = {
  collection: string;
  reason: string;
  content_preview: string;
};

export type DetectedObject = {
  label: string;
  confidence: number; // 0.0 - 1.0
};

/** windows/objects/ocr are nullable by contract — the VLM may see none of them. */
export type VisionUpdatePayload = {
  description: string;
  /** Always a single-element list containing the active app's name. */
  windows: string[] | null;
  objects: DetectedObject[] | null;
  ocr: string[] | null;
};

export type SystemStatsPayload = {
  cpu_percent: number;
  memory_percent: number;
  memory_used_gb: number;
  memory_total_gb: number;
  disk_percent: number;
  disk_used_gb: number;
  disk_total_gb: number;
  net_down_bps: number;
  net_up_bps: number;
  temp_c: number | null;
};

export type STTPartialPayload = {
  text: string;
  is_final: boolean;
};

export type OcrReadPayload = {
  /** One line of text recognized in Read mode. */
  text: string;
  confidence: number;
  source: string;
};

export type TokenStreamPayload = {
  agent_name: string;
  token: string;
  /** Cumulative response text — use this, never accumulate `token` yourself. */
  full_content: string;
};

/** Wire shape: _serialize flattens the nested ReliabilityMetrics dataclass
 *  into top-level metric_* keys (ws_ui.py) — this map reflects that. */
export type ConfidencePayload = {
  request_id: string;
  metric_tool_success_rate: number;
  metric_avg_response_sec: number;
  metric_memory_recall_pct: number;
  metric_hallucination_passed: number;
  metric_hallucination_total: number;
  details: Record<string, unknown> | null;
};

export type ToolStartedPayload = {
  tool_name: string;
  args: Record<string, unknown>;
};

export type ToolFinishedPayload = {
  tool_name: string;
  status: string;
  result: string | null;
  error: string | null;
  latency_ms: number;
};

export type WakeHeardPayload = {
  peak: number; // peak amplitude of the captured audio buffer, 0..32767
};

export type PhoneFramePayload = {
  frame_id: number;      // monotonic; fetch /vision/phone_frame when it changes
  timestamp: number;     // server receive time (epoch seconds)
  mode: string;          // "navigate" | "scan" | "read" | "idle"
  fps_received: number;
};

export type ObstaclePayload = {
  label: string;
  direction: "left" | "straight" | "right";
  distance_m: number;
  confidence: number;
  priority: "critical" | "warning";
  /** Bbox filled the frame vertically — the object is closer than the pinhole
   *  model can measure, so distance_m is a stand-in and must not be shown as
   *  a reading. Optional: older backends don't send it. */
  clipped?: boolean;
};

export type ModeChangePayload = {
  mode: string; // "navigate" | "scan" | "read" | "idle"
};

export type HapticPayload = {
  pulses: number; // 1 = critical, 2 = warning
};

/** Phase 4 diagnostics. Every numeric field is -1 when the backend could not
 *  measure it — that sentinel exists so the UI never renders an unmeasured
 *  value as a real 0. Render it as an em-dash, never as a number. */
export type VisionHealthPayload = {
  fps_received: number;
  fps_processed: number;
  detector_latency_ms: number;
  tts_queue_depth: number;
  /** fps-throttle drops — normal and expected at 2fps. */
  dropped_frames: number;
  /** End-to-end frame age (server receive minus phone capture, clock-offset
   *  corrected). -1 until the clock handshake with the phone completes.
   *  Unlike every other field here a NEGATIVE value can be a real reading —
   *  it means the clock-offset estimate has the wrong sign — so gate on
   *  frame_age_measured, never on the sign. */
  frame_age_ms: number;
  /** Whether frame_age_ms is a reading at all. Optional: older backends
   *  don't send it, and the caller falls back to the sign test. */
  frame_age_measured?: boolean;
  /** Cumulative frames dropped for exceeding the 1.5s staleness gate. Always
   *  >= 0, never -1. Distinct from dropped_frames: this one means the link is
   *  too slow to guide someone safely. */
  frames_dropped_stale: number;
  mode: string;
};

export type UiEventPayloadMap = {
  ai_metrics: AIMetricsPayload;
  wake_heard: WakeHeardPayload;
  phone_frame: PhoneFramePayload;
  obstacle: ObstaclePayload;
  mode_change: ModeChangePayload;
  haptic: HapticPayload;
  vision_health: VisionHealthPayload;
  intent_resolved: IntentResolvedPayload;
  agent_thinking: AgentThinkingPayload;
  agent_reasoning: AgentReasoningPayload;
  agent_completed: AgentCompletedPayload;
  provider_degraded: ProviderDegradedPayload;
  memory_hit: MemoryHitPayload;
  memory_write_failed: MemoryWriteFailedPayload;
  system_stats: SystemStatsPayload;
  vision_update: VisionUpdatePayload;
  stt_partial: STTPartialPayload;
  ocr_read: OcrReadPayload;
  token_stream: TokenStreamPayload;
  confidence: ConfidencePayload;
  tool_started: ToolStartedPayload;
  tool_finished: ToolFinishedPayload;
};

export type UiEventType = keyof UiEventPayloadMap;
