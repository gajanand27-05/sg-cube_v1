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

export type UiEventPayloadMap = {
  ai_metrics: AIMetricsPayload;
  intent_resolved: IntentResolvedPayload;
  agent_thinking: AgentThinkingPayload;
  agent_reasoning: AgentReasoningPayload;
  agent_completed: AgentCompletedPayload;
  provider_degraded: ProviderDegradedPayload;
  system_stats: SystemStatsPayload;
};

export type UiEventType = keyof UiEventPayloadMap;
