// @vitest-environment jsdom
//
// Per-file rather than a config glob: vitest 4 dropped environmentMatchGlobs,
// and the docblock keeps the DOM cost on the two files that need a DOM instead
// of every pure-logic test in the project.
/**
 * What the vision panel actually RENDERS.
 *
 * The rule these follow, learned the hard way on this project: assert named
 * content, not boxes. A previous layout check asserted "panels inside
 * viewport" and passed while every panel was clipping half its rows. So every
 * assertion here names a string a person would read on screen.
 *
 * All three behaviours under test were introduced on 2026-08-13 and shipped
 * verified by `tsc --noEmit` alone:
 *   - a clipped obstacle must read "very close", never a fabricated "0.5m"
 *   - frame age must gate on frame_age_measured, NOT on the sign, because a
 *     negative age is a real reading there
 *   - read mode's recognized text must appear at all (ocr_read had no HUD
 *     consumer whatsoever until that day)
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The real hooks open a WebSocket on mount. Replace them with controllable
// stand-ins so these tests are about rendering, not transport — the transport
// is covered for real in tests/test_ocr_read_reaches_the_hud.py.
const events = new Map<string, unknown>();
const listeners = new Map<string, (p: unknown) => void>();

vi.mock("@/hooks/useUiEvents", () => ({
  useUiEvent: (type: string) => events.get(type) ?? null,
  useUiEventEnvelope: (type: string) => {
    const payload = events.get(type);
    return payload ? { type, timestamp: new Date().toISOString(), payload } : null;
  },
  useUiEventListener: (type: string, handler: (p: unknown) => void) => {
    listeners.set(type, handler);
  },
  useUiConnectionState: () => "open",
}));

import { ReadModeTranscript, VisionModeHealthRow } from "./VisionModulePanel";

afterEach(() => {
  // Without this, render() leaves the previous test's markup in document.body
  // and queries match it: the negative-age test failed because test 1's "age —"
  // was still mounted. Auto-cleanup only happens when vitest globals are on.
  cleanup();
  events.clear();
  listeners.clear();
});

describe("VisionModeHealthRow — frame age", () => {
  it("shows an em-dash when the backend says it could not measure", () => {
    events.set("vision_health", {
      fps_received: 2, fps_processed: 2, detector_latency_ms: 50,
      dropped_frames: 0, tts_queue_depth: 0, frames_dropped_stale: 0,
      mode: "navigate", frame_age_ms: -1, frame_age_measured: false,
    });
    render(<VisionModeHealthRow />);
    expect(screen.getByText(/age —/)).toBeTruthy();
  });

  it("shows a NEGATIVE age as a real reading, not as unmeasured", () => {
    // The bug this guards: measured()'s `< 0` test rendered a wrong-sign clock
    // offset — the one fault vision-health cannot otherwise detect — as the
    // same em-dash as "handshake hasn't landed".
    events.set("vision_health", {
      fps_received: 2, fps_processed: 2, detector_latency_ms: 50,
      dropped_frames: 0, tts_queue_depth: 0, frames_dropped_stale: 0,
      mode: "navigate", frame_age_ms: -42, frame_age_measured: true,
    });
    render(<VisionModeHealthRow />);
    expect(screen.getByText(/age -42ms/)).toBeTruthy();
    expect(screen.queryByText(/age —/)).toBeNull();
  });

  it("falls back to the sign test for a backend that omits the flag", () => {
    events.set("vision_health", {
      fps_received: 2, fps_processed: 2, detector_latency_ms: 50,
      dropped_frames: 0, tts_queue_depth: 0, frames_dropped_stale: 0,
      mode: "navigate", frame_age_ms: 120,
    });
    render(<VisionModeHealthRow />);
    expect(screen.getByText(/age 120ms/)).toBeTruthy();
  });

  it("renders an unmeasured drop count as an em-dash, not as zero drops", () => {
    // vision_health._ingestor_dropped used to return 0 on failure, so an
    // unreachable ingestor read as a perfectly healthy stream.
    events.set("vision_health", {
      fps_received: 2, fps_processed: 2, detector_latency_ms: 50,
      dropped_frames: -1, tts_queue_depth: 0, frames_dropped_stale: 0,
      mode: "navigate", frame_age_ms: 10, frame_age_measured: true,
    });
    render(<VisionModeHealthRow />);
    expect(screen.getByText(/drop —/)).toBeTruthy();
  });
});

describe("ReadModeTranscript", () => {
  it("renders nothing before any text has been read", () => {
    const { container } = render(<ReadModeTranscript />);
    expect(container.textContent).toBe("");
  });

  it("shows a recognized line once one arrives", () => {
    render(<ReadModeTranscript />);
    const handler = listeners.get("ocr_read")!;
    expect(handler).toBeTruthy();
    // act(): the handler is a subscription callback firing outside React's
    // render cycle, exactly as a real socket message does. Without it the
    // state update never flushes and the assertion reads a stale DOM.
    act(() => handler({ text: "PLATFORM 4", confidence: 0.91, source: "ocr" }));
    expect(screen.getByText("PLATFORM 4")).toBeTruthy();
  });

  it("keeps the digit — the number is the whole point of the sign", () => {
    render(<ReadModeTranscript />);
    act(() => listeners.get("ocr_read")!({ text: "GATE B 12", confidence: 0.9, source: "ocr" }));
    expect(screen.getByText("GATE B 12")).toBeTruthy();
  });
});
