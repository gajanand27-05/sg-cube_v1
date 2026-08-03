import { useUiEvent } from "@/hooks/useUiEvents";

/** Two-lane live transcript: You (STT partials) on top, Onyx (token stream)
 *  below. Both use the latest-payload hook so values survive a remount.
 *
 *  Onyx lane renders `full_content` — the backend's own accumulated text.
 *  Accumulating `token` here reintroduces the JSON-envelope bug the handoff
 *  warned about; the payload is already the full response.
 */
export function LiveTranscriptionPanel() {
  const stt = useUiEvent("stt_partial");
  const stream = useUiEvent("token_stream");

  const youText = stt?.text ?? "";
  const youProvisional = stt === null || !stt.is_final;
  const onyxText = stream?.full_content ?? "";

  return (
    <div className="flex flex-col gap-3 min-h-0 h-full">
      <div className="flex flex-col gap-1 min-w-0 flex-1 overflow-hidden">
        <span className="hud-label">You</span>
        <div className="flex-1 min-h-0 overflow-y-auto pr-1">
          {youText.length === 0 ? (
            <span className="font-mono text-[10px] text-hud-text-dim">
              listening…
            </span>
          ) : (
            <span
              className={`font-mono text-[10px] leading-relaxed line-clamp-3 ${
                youProvisional
                  ? "text-hud-text-dim italic"
                  : "text-hud-text"
              }`}
            >
              {youText}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1 min-w-0 flex-1 overflow-hidden border-t border-hud-border-dim pt-2">
        <span className="hud-label">Onyx</span>
        <div className="flex-1 min-h-0 overflow-y-auto pr-1">
          {onyxText.length === 0 ? (
            <span className="font-mono text-[10px] text-hud-text-dim">
              awaiting response…
            </span>
          ) : (
            <span className="font-mono text-[10px] text-hud-text leading-relaxed line-clamp-3">
              {onyxText}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
