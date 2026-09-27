// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The panel's headline is how long the user waited for Onyx to start
// talking (reply_latency.first_word_ms). The provider's inference time — the
// whole generation, mostly spoken over — is only the secondary line. It used
// to be the headline, and read as a 4.6s delay nobody actually waited.

const listeners: Record<string, (p: unknown) => void> = {};
let metrics: Record<string, unknown> | null = null;

vi.mock("@/hooks/useUiEvents", () => ({
  useUiConnectionState: () => "open",
  useUiEvent: (type: string) => (type === "ai_metrics" ? metrics : null),
  useUiEventCounter: () => 0,
  useUiEventEnvelope: () => null,
  useUiEventListener: (type: string, h: (p: unknown) => void) => {
    listeners[type] = h;
  },
}));

import { AICorePanel } from "./AICorePanel";

afterEach(() => {
  cleanup();
  metrics = null;
});

describe("AICorePanel latency", () => {
  it("headlines time to first word and demotes full generation", () => {
    metrics = {
      tokens_per_second: 10, latency_ms: 4578, inference_ms: 4578,
      queue_depth: 0, tool_calls: 0, active_model: "gemma4:31b",
    };
    render(<AICorePanel />);
    act(() => listeners["reply_latency"]({ first_word_ms: 1940, request_id: "r1" }));
    expect(screen.getByTestId("first-word").textContent).toContain("First word");
    expect(screen.getByTestId("first-word").textContent).toContain("1.9s");
    expect(screen.getByTestId("full-reply").textContent).toBe("full reply 4578ms · 10.0 tok/s");
  });

  it("names a failover on the reply it happened to, and only then", () => {
    metrics = {
      tokens_per_second: 20, latency_ms: 900, inference_ms: 900, queue_depth: 0,
      tool_calls: 1, active_model: "qwen2.5:7b", failed_over_from: "gemma4:31b",
    };
    const { rerender } = render(<AICorePanel />);
    expect(screen.getByTestId("failover").textContent).toBe("fallback (gemma4:31b failed)");
    metrics = { ...metrics, active_model: "gemma4:31b", failed_over_from: "" };
    rerender(<AICorePanel />);
    expect(screen.queryByTestId("failover")).toBeNull();
  });

  it("shows a dash until a reply has been spoken", () => {
    render(<AICorePanel />);
    expect(screen.getByTestId("first-word").textContent).toContain("—");
  });
});
