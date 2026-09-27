// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Recordings are opt-in: the indicator says whether the user's voice is being
// kept, the checkbox switches it, and "Delete all recordings" asks inside the
// HUD before deleting (never a browser dialog, which would block the page).

const calls: { path: string; init?: RequestInit }[] = [];
let status = { enabled: false, recordings: 3, bytes: 2_500_000, retention_days: 7, max_per_kind: 500 };

vi.mock("@/hooks/useUiEvents", () => ({
  hudFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    if (path === "/api/recordings" && init?.method === "POST") {
      status = { ...status, enabled: JSON.parse(String(init.body)).enabled };
    }
    if (path === "/api/recordings/delete") {
      const deleted = status.recordings;
      status = { ...status, recordings: 0, bytes: 0 };
      return new Response(JSON.stringify({ ...status, deleted }));
    }
    return new Response(JSON.stringify(status));
  },
}));

import { RecordingsControl } from "./RecordingsControl";

afterEach(() => {
  cleanup();
  calls.length = 0;
  status = { enabled: false, recordings: 3, bytes: 2_500_000, retention_days: 7, max_per_kind: 500 };
});

describe("RecordingsControl", () => {
  it("shows off, then the opt-in wording, and turns recording on", async () => {
    render(<RecordingsControl />);
    const indicator = await screen.findByTestId("recordings-indicator");
    expect(indicator.textContent).toContain("Recordings off");
    fireEvent.click(indicator);
    const box = screen.getByLabelText(
      "Keep recordings of my voice to improve recognition (stays on this PC)",
    );
    fireEvent.click(box);
    await waitFor(() =>
      expect(screen.getByTestId("recordings-indicator").textContent).toContain("Recording kept"),
    );
    expect(calls.some((c) => c.init?.method === "POST" && c.path === "/api/recordings")).toBe(true);
  });

  it("deletes only after a confirmation inside the HUD", async () => {
    render(<RecordingsControl />);
    fireEvent.click(await screen.findByTestId("recordings-indicator"));
    fireEvent.click(screen.getByText("Delete all recordings"));
    expect(calls.some((c) => c.path === "/api/recordings/delete")).toBe(false);
    expect(screen.getByText(/Delete all 3 recordings\?/)).toBeTruthy();
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(screen.getByText("Deleted 3 recordings.")).toBeTruthy());
  });
});
