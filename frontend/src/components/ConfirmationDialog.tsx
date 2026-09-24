import { useEffect, useState } from "react";
import { sendUiMessage, useUiEventListener } from "@/hooks/useUiEvents";
import type { ConfirmationRequestPayload } from "@/lib/uiEvents";

/**
 * Yes/no for an action the assistant is waiting on.
 *
 * The same question is also open to voice ("yes" / "no"); whichever answers
 * first consumes it, and the backend then broadcasts confirmation_resolved,
 * which closes this dialog either way. An answer echoes the request's id AND
 * digest — the digest is a hash of the exact tool calls — so it can only ever
 * approve what is shown here. Running out of time is a refusal: the dialog
 * just closes, and the backend runs nothing.
 */
export function ConfirmationDialog() {
  const [pending, setPending] = useState<ConfirmationRequestPayload | null>(null);
  const [deadline, setDeadline] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [sent, setSent] = useState(false);

  useUiEventListener("confirmation_request", (p) => {
    setPending(p);
    setSent(false);
    setDeadline(Date.now() + p.expires_in_s * 1000);
  });
  useUiEventListener("confirmation_resolved", (p) => {
    setPending((cur) => (cur && cur.id === p.id ? null : cur));
  });

  useEffect(() => {
    if (!pending) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [pending]);

  const left = Math.max(0, Math.ceil((deadline - now) / 1000));
  useEffect(() => {
    if (pending && deadline && now >= deadline) setPending(null);
  }, [pending, deadline, now]);

  if (!pending) return null;

  const answer = (decision: "yes" | "no") => {
    if (sendUiMessage({ type: "confirm_response", id: pending.id, digest: pending.digest, decision })) {
      setSent(true);
    }
  };

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div
        className={`w-full max-w-lg rounded-lg border bg-slate-950 p-5 shadow-xl ${
          pending.critical ? "border-red-500/70" : "border-cyan-500/50"
        }`}
      >
        <h2 id="confirm-title" className="text-sm font-semibold uppercase tracking-wide text-slate-300">
          {pending.critical ? "High-risk action" : "Confirm action"}
        </h2>
        <p className="mt-3 text-slate-100">{pending.prompt}</p>
        {pending.details.length > 0 && (
          <ul className="mt-3 max-h-48 overflow-auto rounded bg-slate-900 p-2 font-mono text-xs text-slate-200">
            {pending.details.map((d) => (
              <li key={d} className="break-all py-0.5">{d}</li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-slate-400">
          You can also answer by voice. Refused automatically in {left}s.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            disabled={sent}
            onClick={() => answer("no")}
            className="rounded border border-slate-600 px-4 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            No
          </button>
          <button
            type="button"
            disabled={sent}
            onClick={() => answer("yes")}
            className={`rounded px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 ${
              pending.critical ? "bg-red-600 hover:bg-red-500" : "bg-cyan-600 hover:bg-cyan-500"
            }`}
          >
            Yes
          </button>
        </div>
      </div>
    </div>
  );
}
