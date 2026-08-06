import { useEffect, useRef } from "react";
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
      <FollowLane label="You" empty="listening…" text={youText}
        textClass={youProvisional ? "text-hud-text-dim italic" : "text-hud-text"} />
      <FollowLane label="Onyx" empty="awaiting response…" text={onyxText}
        textClass="text-hud-text"
        className="border-t border-hud-border-dim pt-2" />
    </div>
  );
}

/** A lane that scrolls internally and follows its newest text — pinned to the
 *  bottom while streaming, released as soon as the user scrolls up. */
function FollowLane({
  label,
  text,
  empty,
  textClass,
  className = "",
}: {
  label: string;
  text: string;
  empty: string;
  textClass: string;
  className?: string;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  useEffect(() => {
    const el = boxRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [text]);

  // Unpin ONLY on user intent (wheel-up / touch drag). The scroll handler
  // never unpins: programmatic scrollTop writes fire scroll events
  // asynchronously, by which time streamed content has grown again and the
  // "are we at the bottom?" test fails spuriously — that race froze the lane
  // mid-stream. onScroll only re-pins when the user returns to the bottom.
  return (
    <div className={`flex flex-col gap-1 min-w-0 flex-1 min-h-0 overflow-hidden ${className}`}>
      <span className="hud-label">{label}</span>
      <div
        ref={boxRef}
        onWheel={(e) => {
          if (e.deltaY < 0) pinnedRef.current = false;
        }}
        onTouchMove={() => {
          pinnedRef.current = false;
        }}
        onScroll={() => {
          const el = boxRef.current;
          if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 8) {
            pinnedRef.current = true;
          }
        }}
        className="flex-1 min-h-0 overflow-y-auto pr-1"
      >
        {text.length === 0 ? (
          <span className="font-mono text-[10px] text-hud-text-dim">{empty}</span>
        ) : (
          <span className={`font-mono text-[10px] leading-relaxed whitespace-pre-wrap ${textClass}`}>
            {text}
          </span>
        )}
      </div>
    </div>
  );
}
