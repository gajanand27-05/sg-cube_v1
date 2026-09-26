import { useEffect, useState } from "react";
import { useUiEventListener } from "@/hooks/useUiEvents";
import type { TypingFocusPayload } from "@/lib/uiEvents";

/**
 * After a HUD "yes" to type_text, the HUD itself has focus — so the backend
 * waits (about 10 s) for the user to click into the approved window before
 * typing anything. This banner says which window, with the countdown. It
 * closes when typing starts, and on timeout the backend cancels and says so.
 */
export function TypingFocusBanner() {
  const [waiting, setWaiting] = useState<TypingFocusPayload | null>(null);
  const [deadline, setDeadline] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  useUiEventListener("typing_focus", (p) => {
    if (p.state === "waiting") {
      setWaiting(p);
      setDeadline(Date.now() + p.timeout_s * 1000);
    } else {
      setWaiting(null);
    }
  });

  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [waiting]);

  if (!waiting) return null;
  const left = Math.max(0, Math.ceil((deadline - now) / 1000));

  return (
    <div
      role="status"
      aria-live="assertive"
      className="fixed left-1/2 top-4 z-50 -translate-x-1/2 rounded-lg border border-cyan-500/60 bg-slate-950 px-5 py-3 text-sm text-slate-100 shadow-xl"
    >
      Click into <strong>{waiting.title || "(untitled)"}</strong> ({waiting.process}) to start
      typing — {left}s
    </div>
  );
}
