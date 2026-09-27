import { useCallback, useEffect, useState } from "react";
import { hudFetch } from "@/hooks/useUiEvents";
import { cn } from "@/lib/cn";

// Recordings of the user's voice (the capture archive). Off by default: it
// keeps audio of what the microphone hears at home. This shows when it is on,
// switches it, and deletes everything — with the delete confirmed inside the
// HUD, never through a browser dialog.

type Status = {
  enabled: boolean;
  recordings: number;
  bytes: number;
  retention_days: number;
  max_per_kind: number;
};

const OPT_IN = "Keep recordings of my voice to improve recognition (stays on this PC)";

function mb(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function RecordingsControl() {
  const [status, setStatus] = useState<Status | null>(null);
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await hudFetch("/api/recordings");
      if (r.ok) setStatus((await r.json()) as Status);
    } catch {
      /* backend down: the control just shows nothing */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (enabled: boolean) => {
    const r = await hudFetch("/api/recordings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (r.ok) setStatus((await r.json()) as Status);
  };

  const deleteAll = async () => {
    const r = await hudFetch("/api/recordings/delete", { method: "POST" });
    if (r.ok) {
      const body = (await r.json()) as Status & { deleted: number };
      setStatus(body);
      setNote(`Deleted ${body.deleted} recording${body.deleted === 1 ? "" : "s"}.`);
    }
    setConfirming(false);
  };

  if (status === null) return null;

  return (
    <div className="relative">
      <button
        type="button"
        data-testid="recordings-indicator"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1.5 px-2 py-1 rounded-sm border text-[10px] uppercase tracking-wider",
          status.enabled
            ? "border-hud-danger text-hud-danger"
            : "border-hud-border-dim text-hud-text-dim",
        )}
        title={status.enabled ? "Your voice is being recorded and kept on this PC" : "Recordings are off"}
      >
        <span
          className={cn("inline-block w-2 h-2 rounded-full", status.enabled ? "bg-hud-danger" : "bg-hud-text-dim")}
        />
        {status.enabled ? "Recording kept" : "Recordings off"}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Recordings"
          className="absolute bottom-full mb-2 left-0 w-80 p-3 rounded-sm border border-hud-border bg-bg-panel text-xs text-hud-text flex flex-col gap-2"
        >
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={status.enabled}
              onChange={(e) => void toggle(e.target.checked)}
            />
            <span>{OPT_IN}</span>
          </label>
          <div className="text-hud-text-dim">
            Kept for {status.retention_days} days, at most {status.max_per_kind} of each kind.
            Now: {status.recordings} recording{status.recordings === 1 ? "" : "s"}, {mb(status.bytes)}.
          </div>
          {confirming ? (
            <div className="flex items-center gap-2">
              <span>Delete all {status.recordings} recordings? This can't be undone.</span>
              <button type="button" className="text-hud-danger underline" onClick={() => void deleteAll()}>
                Delete
              </button>
              <button type="button" className="underline" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="self-start text-hud-danger underline disabled:opacity-40"
              disabled={status.recordings === 0}
              onClick={() => setConfirming(true)}
            >
              Delete all recordings
            </button>
          )}
          {note && <div className="text-hud-text-dim">{note}</div>}
        </div>
      )}
    </div>
  );
}
