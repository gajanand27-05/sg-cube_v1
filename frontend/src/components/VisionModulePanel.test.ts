/**
 * `measured()` — the rule that keeps the HUD from inventing a reading.
 *
 * The backend sends -1 for anything it could not measure, precisely so the UI
 * never renders it as a real 0: "0 fps" reads as a measured zero, i.e. a
 * healthy-but-idle stream, which is the exact lie the vision-health module
 * exists to prevent.
 *
 * The subtlety worth pinning is the field this helper must NOT be used on.
 * frame_age_ms is the one health value where a NEGATIVE number is a genuine
 * reading — it means the phone-clock offset was estimated with the wrong sign,
 * the single fault vision-health cannot otherwise detect — and routing it
 * through measured() rendered that fault as the same em-dash as "handshake
 * hasn't landed yet". VisionModulePanel gates that field on the backend's
 * explicit frame_age_measured flag instead.
 */
import { describe, expect, it } from "vitest";

import { measured } from "./VisionModulePanel";

describe("measured", () => {
  it("passes real values through", () => {
    expect(measured(0)).toBe(0);
    expect(measured(1.5)).toBe(1.5);
  });

  it("treats the -1 sentinel as unmeasured", () => {
    expect(measured(-1)).toBeNull();
  });

  it("treats any negative as unmeasured", () => {
    expect(measured(-0.5)).toBeNull();
    expect(measured(-999)).toBeNull();
  });

  it("treats absent and non-finite as unmeasured", () => {
    expect(measured(undefined)).toBeNull();
    expect(measured(NaN)).toBeNull();
    expect(measured(Infinity)).toBeNull();
  });

  it("keeps a measured zero distinct from an unmeasured one", () => {
    // The whole point. 0 means "counted, and it was zero"; -1 means "could not
    // count". Collapsing them is how a dead ingestor renders as a healthy one —
    // which is a bug that shipped, in vision_health._ingestor_dropped.
    expect(measured(0)).toBe(0);
    expect(measured(-1)).toBeNull();
    expect(measured(0)).not.toBe(measured(-1));
  });

  it("is the WRONG gate for frame_age_ms, by design", () => {
    // Documented as a test so the exception is not rediscovered as a bug: a
    // real -42ms frame age means a wrong-sign clock offset, and measured()
    // would erase it. VisionModulePanel uses frame_age_measured for that field.
    const realNegativeReading = -42;
    expect(measured(realNegativeReading)).toBeNull();
  });
});
