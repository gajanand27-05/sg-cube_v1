import { useEffect, useReducer, useRef } from "react";
import { useUiEvent } from "@/hooks/useUiEvents";
import { initialTranscript, reduceTranscript } from "@/lib/transcriptTurn";

/** Two-lane live transcript: You (STT) on top, Onyx (the reply) below.
 *
 *  The two lanes are fed through a turn reducer rather than rendered straight
 *  from their latest payloads. Independently-latest values put a question and
 *  an unrelated answer side by side — a text-path turn publishes only
 *  `token_stream`, so it replaced the Onyx lane while a stale voice
 *  transcript stayed above it, and a failed turn left the PREVIOUS answer on
 *  screen looking like a reply to the question that had just failed. See
 *  lib/transcriptTurn.ts for the pairing rules.
 *
 *  Onyx renders `prose`, never `full_content`: the latter is the raw
 *  accumulated stream, which for the planner is a JSON envelope. Rendering it
 *  is what printed `{"final_response": "..."}` on the HUD.
 */
export function LiveTranscriptionPanel() {
  const stt = useUiEvent("stt_partial");
  const stream = useUiEvent("token_stream");
  const completed = useUiEvent("agent_completed");
  const [turn, dispatch] = useReducer(reduceTranscript, initialTranscript);

  useEffect(() => {
    if (stt) dispatch({ kind: "stt", text: stt.text, isFinal: !!stt.is_final });
  }, [stt]);

  useEffect(() => {
    if (!stream) return;
    // Fall back to full_content only if the backend predates `prose`; a
    // visible envelope is still better than a silently empty lane, and it
    // makes a version mismatch obvious rather than invisible.
    dispatch({
      kind: "stream",
      prose: stream.prose ?? stream.full_content ?? "",
      requestId: stream.request_id ?? "",
    });
  }, [stream]);

  useEffect(() => {
    if (completed) dispatch({ kind: "done" });
  }, [completed]);

  const youText = turn.you;
  const youProvisional = turn.youProvisional;
  const onyxText = turn.onyx;

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
