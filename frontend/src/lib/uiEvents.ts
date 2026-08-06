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

export type UiEventPayloadMap = {
  ai_metrics: AIMetricsPayload;
  wake_heard: WakeHeardPayload;
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
  token_stream: TokenStreamPayload;
  confidence: ConfidencePayload;
  tool_started: ToolStartedPayload;
  tool_finished: ToolFinishedPayload;
};

export type UiEventType = keyof UiEventPayloadMap;
