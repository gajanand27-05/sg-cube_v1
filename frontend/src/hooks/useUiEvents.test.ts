/**
 * The HUD's crash guard, which is also its quietest failure mode.
 *
 * isValidPayload DROPS any event missing a declared field, deliberately, so a
 * renamed backend field cannot ship a TypeError into render. The cost is that
 * the same rename blanks a panel with no error anywhere: the backend logs a
 * successful publish, the socket carries it, the HUD discards it on arrival.
 *
 * Until now the frontend had no test runner at all, so every rule below was
 * enforced only by reading. Four backend fields crossed this boundary on
 * 2026-08-13 (ObstacleEvent.clipped, VisionHealthEvent.frame_age_measured, the
 * whole ocr_read payload) verified only by `tsc --noEmit` — which proves the
 * types compile, not that the gate does what it claims.
 *
 * tests/test_event_contract.py guards the other half: that these declared
 * fields still exist on the Python dataclasses.
 */
import { describe, expect, it } from "vitest";

import { isValidPayload } from "./useUiEvents";

describe("isValidPayload", () => {
  it("accepts a complete payload", () => {
    expect(isValidPayload("obstacle", {
      label: "person", direction: "left", distance_m: 1.2, priority: "critical",
    })).toBe(true);
  });

  it("drops a payload missing a required field", () => {
    // This is the silent-blanking bug in miniature: distance_m renamed on the
    // backend, panel goes empty, nothing logs an error.
    expect(isValidPayload("obstacle", {
      label: "person", direction: "left", priority: "critical",
    })).toBe(false);
  });

  it("drops NaN where a number is required", () => {
    // NaN passes `typeof === "number"` but renders as "NaN" through toFixed,
    // which is why the check is Number.isFinite and not typeof.
    expect(isValidPayload("obstacle", {
      label: "person", direction: "left", distance_m: NaN, priority: "critical",
    })).toBe(false);
  });

  it("accepts negative numbers, because -1 is the unmeasured sentinel", () => {
    // The backend sends -1 for anything it could not measure. Rejecting
    // negatives here would drop every event during startup, when several
    // fields are legitimately unmeasured.
    expect(isValidPayload("vision_health", {
      fps_received: -1, fps_processed: -1, detector_latency_ms: -1,
      dropped_frames: -1, frame_age_ms: -1, frames_dropped_stale: 0, mode: "idle",
    })).toBe(true);
  });

  it("lets unknown event types through untouched", () => {
    // The UI never reads them; dropping them would silently break any future
    // consumer before it was written.
    expect(isValidPayload("some_future_event", { anything: 1 })).toBe(true);
  });

  it("rejects non-objects rather than throwing on them", () => {
    for (const bad of [null, undefined, 42, "text", []]) {
      expect(isValidPayload("obstacle", bad)).toBe(false);
    }
  });

  it("accepts the ocr_read payload read mode actually sends", () => {
    // Added 2026-08-13. The backend probe (tests/test_ocr_read_reaches_the_hud)
    // proves this shape crosses the wire; this proves the HUD keeps it.
    expect(isValidPayload("ocr_read", {
      text: "PLATFORM 4", confidence: 0.91, source: "ocr",
    })).toBe(true);
    expect(isValidPayload("ocr_read", { text: "PLATFORM 4" })).toBe(false);
  });

  it("requires a string to actually be a string", () => {
    expect(isValidPayload("mode_change", { mode: "read" })).toBe(true);
    expect(isValidPayload("mode_change", { mode: 3 })).toBe(false);
  });
});
