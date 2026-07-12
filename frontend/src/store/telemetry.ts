// Typed telemetry contracts — mirror backend/daemon/ui_events.py dataclasses.
// Backend and frontend evolve together from these shapes (one source of truth).

export interface MemoryHitItem {
  title: string
  score: number // 0..1 combined relevance
  source: string
}

export interface VisionObject {
  label: string
  confidence: number // 0..1
}

export interface AIMetrics {
  tokens_per_second: number
  latency_ms: number
  inference_ms: number
  queue_depth: number
  tool_calls: number
  active_model: string
}
