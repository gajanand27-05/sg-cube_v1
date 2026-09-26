// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const handlers: Record<string, (p: unknown) => void> = {};
vi.mock("@/hooks/useUiEvents", () => ({
  useUiEventListener: (type: string, h: (p: unknown) => void) => {
    handlers[type] = h;
  },
}));

import { TypingFocusBanner } from "./TypingFocusBanner";

const WAIT = {
  state: "waiting", title: "todo.txt - Notepad", process: "notepad.exe",
  timeout_s: 10, typed: 0, total: 5,
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("TypingFocusBanner", () => {
  it("names the window and counts down", () => {
    render(<TypingFocusBanner />);
    act(() => handlers["typing_focus"](WAIT));
    expect(screen.getByRole("status").textContent).toContain("Click into todo.txt - Notepad (notepad.exe) to start typing — 10s");
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("status").textContent).toContain("7s");
  });

  it("closes when typing starts or the wait is cancelled", () => {
    render(<TypingFocusBanner />);
    act(() => handlers["typing_focus"](WAIT));
    act(() => handlers["typing_focus"]({ ...WAIT, state: "typing" }));
    expect(screen.queryByRole("status")).toBeNull();
    act(() => handlers["typing_focus"](WAIT));
    act(() => handlers["typing_focus"]({ ...WAIT, state: "cancelled" }));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
