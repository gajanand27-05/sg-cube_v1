/** Pairs a question with its own answer in the live transcript.
 *
 *  The two lanes used to be independent latest-value subscriptions: You showed
 *  the last `stt_partial`, Onyx showed the last `token_stream`, and nothing
 *  tied them to the same turn. A text-path turn publishes only `token_stream`,
 *  so it overwrote the Onyx lane and left the previous voice turn's transcript
 *  sitting above it — reading as a question-and-answer pair that never
 *  happened. The same asymmetry means a dropped or failed turn silently keeps
 *  the PREVIOUS answer on screen, so every failure looks like the assistant
 *  answering the wrong question. That is the expensive version of this bug:
 *  it misleads you exactly when you are trying to diagnose something.
 *
 *  Kept as a pure reducer so the pairing rules can be tested directly. The
 *  rules are about ordering, not identity, because `stt_partial` is published
 *  before a request_id exists — transcription precedes the turn it starts.
 */

export type TranscriptState = {
  you: string;
  /** Still mid-utterance — rendered dim/italic. */
  youProvisional: boolean;
  onyx: string;
  /** A user utterance has begun and has not yet been answered. */
  turnOpen: boolean;
  /** request_id of the answer currently displayed; "" when none. */
  streamId: string;
};

export const initialTranscript: TranscriptState = {
  you: "",
  youProvisional: true,
  onyx: "",
  turnOpen: false,
  streamId: "",
};

export type TranscriptEvent =
  | { kind: "stt"; text: string; isFinal: boolean }
  | { kind: "stream"; prose: string; requestId: string }
  | { kind: "done" };

export function reduceTranscript(
  state: TranscriptState,
  ev: TranscriptEvent,
): TranscriptState {
  switch (ev.kind) {
    case "stt": {
      // A new utterance starts a new turn when nothing is awaiting an answer,
      // or when an answer has already been shown for the current one. That
      // second condition is what handles barge-in: speaking over a reply is a
      // new turn even though the old one never formally closed.
      const answerShown = state.streamId !== "";
      if (!state.turnOpen || answerShown) {
        return {
          you: ev.text,
          youProvisional: !ev.isFinal,
          onyx: "",
          turnOpen: true,
          streamId: "",
        };
      }
      return { ...state, you: ev.text, youProvisional: !ev.isFinal };
    }

    case "stream": {
      // Continuation of the answer already on screen.
      if (ev.requestId && ev.requestId === state.streamId) {
        return { ...state, onyx: ev.prose };
      }
      // The answer to the question currently displayed.
      if (state.turnOpen) {
        return { ...state, onyx: ev.prose, streamId: ev.requestId };
      }
      // An answer to a turn this panel never saw the question for — the text
      // path, or a voice turn whose STT was missed. Blank the You lane rather
      // than leave a stale question implying it was asked.
      return {
        you: "",
        youProvisional: true,
        onyx: ev.prose,
        turnOpen: false,
        streamId: ev.requestId,
      };
    }

    case "done":
      return { ...state, turnOpen: false };
  }
}
