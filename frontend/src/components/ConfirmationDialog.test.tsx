// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConfirmationRequestPayload } from "@/lib/uiEvents";

// Drive the dialog by hand: capture the handlers it registers and record
// what it sends, instead of standing up a socket.
const handlers: Record<string, (p: unknown) => void> = {};
const sent: Record<string, unknown>[] = [];
vi.mock("@/hooks/useUiEvents", () => ({
  useUiEventListener: (type: string, h: (p: unknown) => void) => {
    handlers[type] = h;
  },
  sendUiMessage: (m: Record<string, unknown>) => {
    sent.push(m);
    return true;
  },
}));

import { ConfirmationDialog } from "./ConfirmationDialog";

const REQ: ConfirmationRequestPayload = {
  id: "abc", digest: "d1g3st", tool: "delete file",
  prompt: "⚠️ CRITICAL ACTION: I need your explicit permission to delete file.",
  details: ["C:\\Users\\me\\Documents\\old-report.txt"],
  critical: true, expires_in_s: 30,
};

function ask(p: ConfirmationRequestPayload = REQ) {
  act(() => handlers["confirmation_request"](p));
}

beforeEach(() => {
  sent.length = 0;
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ConfirmationDialog", () => {
  it("shows the prompt and the full resolved path", () => {
    render(<ConfirmationDialog />);
    ask();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(screen.getByText(REQ.details[0])).toBeTruthy();
    expect(screen.getByText("High-risk action")).toBeTruthy();
  });

  it("answers with the exact id and digest it was shown", () => {
    render(<ConfirmationDialog />);
    ask();
    fireEvent.click(screen.getByText("Yes"));
    expect(sent).toEqual([{ type: "confirm_response", id: "abc", digest: "d1g3st", decision: "yes" }]);
  });

  it("closes when the backend says it is resolved (voice may have answered)", () => {
    render(<ConfirmationDialog />);
    ask();
    act(() => handlers["confirmation_resolved"]({ id: "abc", outcome: "approved" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("ignores a resolution for a different question", () => {
    render(<ConfirmationDialog />);
    ask();
    act(() => handlers["confirmation_resolved"]({ id: "other", outcome: "expired" }));
    expect(screen.queryByRole("alertdialog")).toBeTruthy();
  });

  it("closes itself when time runs out, sending nothing", () => {
    render(<ConfirmationDialog />);
    ask({ ...REQ, expires_in_s: 2 });
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(sent).toEqual([]);
  });
});
