/**
 * The HUD's crash guard, which is also its quietest failure mode.
 *
 * isValidPayload DROPS any event missing a declared field, deliberately, so a
 * renamed backend field cannot ship a TypeError into render. The cost is that
 * the same rename blanks a panel with no error anywhere: the backend logs a
 * successful publish, the socket carries it, the HUD discards it on arrival.
 *
 * These cases were originally written against obstacle/vision_health/ocr_read,
 * which were removed with the phone-camera subsystem. They are rewritten
 * against surviving events rather than deleted: none of them were ever about
 * the camera, they were about the guard's generic rules, and dropping them
 * would quietly retire the only coverage those rules have.
 *
 * tests/test_event_contract.py guards the other half: that these declared
 * fields still exist on the Python dataclasses.
 */
import { describe, expect, it } from "vitest";

import { isValidPayload } from "./useUiEvents";

describe("isValidPayload", () => {
  it("accepts a complete payload", () => {
    expect(isValidPayload("ai_metrics", {
      tokens_per_second: 42, latency_ms: 800, inference_ms: 610,
      active_model: "gpt-oss:120b",
    })).toBe(true);
  });

  it("drops a payload missing a required field", () => {
    // This is the silent-blanking bug in miniature: inference_ms renamed on the
    // backend, panel goes empty, nothing logs an error.
    expect(isValidPayload("ai_metrics", {
      tokens_per_second: 42, latency_ms: 800, active_model: "gpt-oss:120b",
    })).toBe(false);
  });

  it("drops NaN where a number is required", () => {
    // NaN passes `typeof === "number"` but renders as "NaN" through toFixed,
    // which is why the check is Number.isFinite and not typeof.
    expect(isValidPayload("ai_metrics", {
      tokens_per_second: NaN, latency_ms: 800, inference_ms: 610,
      active_model: "gpt-oss:120b",
    })).toBe(false);
  });

  it("accepts negative numbers, because -1 is the unmeasured sentinel", () => {
    // Backends send -1 for anything they could not measure. Rejecting negatives
    // here would drop every event during startup, when several fields are
    // legitimately unmeasured.
    expect(isValidPayload("ai_metrics", {
      tokens_per_second: -1, latency_ms: -1, inference_ms: -1,
      active_model: "unknown",
    })).toBe(true);
  });

  it("lets unknown event types through untouched", () => {
    // The UI never reads them; dropping them would silently break any future
    // consumer before it was written.
    expect(isValidPayload("some_future_event", { anything: 1 })).toBe(true);
  });

  it("rejects non-objects rather than throwing on them", () => {
    for (const bad of [null, undefined, 42, "text", []]) {
      expect(isValidPayload("ai_metrics", bad)).toBe(false);
    }
  });

  it("requires every declared field, not just the first", () => {
    // A guard that short-circuits after one field would pass this.
    expect(isValidPayload("tool_finished", { tool_name: "open_app" })).toBe(false);
    expect(isValidPayload("tool_finished", {
      tool_name: "open_app", status: "ok",
    })).toBe(true);
  });

  it("requires a string to actually be a string", () => {
    expect(isValidPayload("vision_update", { description: "a browser" })).toBe(true);
    expect(isValidPayload("vision_update", { description: 3 })).toBe(false);
  });
});
