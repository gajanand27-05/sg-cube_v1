import { describe, expect, it } from "vitest";
import {
  initialTranscript,
  reduceTranscript,
  type TranscriptEvent,
  type TranscriptState,
} from "./transcriptTurn";

function run(events: TranscriptEvent[], from: TranscriptState = initialTranscript) {
  return events.reduce(reduceTranscript, from);
}

const stt = (text: string, isFinal = false): TranscriptEvent => ({ kind: "stt", text, isFinal });
const stream = (prose: string, requestId: string): TranscriptEvent => ({ kind: "stream", prose, requestId });
const done: TranscriptEvent = { kind: "done" };

describe("transcript turn pairing", () => {
  it("shows a voice question with its own answer", () => {
    const s = run([stt("what is"), stt("what is the time", true), stream("It is 3pm.", "r1")]);
    expect(s.you).toBe("what is the time");
    expect(s.onyx).toBe("It is 3pm.");
  });

  it("streams the answer without re-clearing the question", () => {
    const s = run([
      stt("what is the time", true),
      stream("It", "r1"),
      stream("It is", "r1"),
      stream("It is 3pm.", "r1"),
    ]);
    expect(s.you).toBe("what is the time");
    expect(s.onyx).toBe("It is 3pm.");
  });

  it("clears the previous answer as soon as the next question starts", () => {
    // Otherwise the old answer sits under the new question, reading as a
    // reply to it — and if the new turn fails, it never gets corrected.
    const s = run([
      stt("what is the time", true),
      stream("It is 3pm.", "r1"),
      done,
      stt("can you hear me"),
    ]);
    expect(s.you).toBe("can you hear me");
    expect(s.onyx).toBe("");
  });

  it("a failed turn shows no answer rather than the previous one", () => {
    // The reported bug: the turn was misheard, dispatched, and produced
    // nothing. The lane must not keep displaying the last good answer.
    const s = run([
      stt("what is the time", true),
      stream("It is 3pm.", "r1"),
      done,
      stt("Thanks for watching. Hear me on X.", true),
      // ...no stream event at all — the turn died.
    ]);
    expect(s.onyx).toBe("");
  });

  it("an answer with no question of its own blanks the question lane", () => {
    // The exact case that produced the screenshot: a text-path turn published
    // token_stream only, overwriting Onyx while a stale voice transcript sat
    // above it. Two unrelated turns, displayed as one exchange.
    const s = run([
      stt("Thanks for watching. Hear me on X.", true),
      done,
      stream("The capital of France is Paris.", "r2"),
    ]);
    expect(s.you).toBe("");
    expect(s.onyx).toBe("The capital of France is Paris.");
  });

  it("barge-in starts a new turn even though the old one never closed", () => {
    const s = run([
      stt("tell me about jupiter", true),
      stream("Jupiter is the largest", "r1"),
      // user interrupts mid-answer; no `done` was ever received
      stt("stop"),
    ]);
    expect(s.you).toBe("stop");
    expect(s.onyx).toBe("");
  });

  it("keeps provisional/final state for styling", () => {
    expect(run([stt("what is")]).youProvisional).toBe(true);
    expect(run([stt("what is the time", true)]).youProvisional).toBe(false);
  });

  it("two consecutive text turns each replace the last", () => {
    const s = run([stream("first", "r1"), done, stream("second", "r2")]);
    expect(s.onyx).toBe("second");
    expect(s.you).toBe("");
  });

  it("is pure — reducing does not mutate the input state", () => {
    const before = { ...initialTranscript };
    reduceTranscript(initialTranscript, stt("hello"));
    expect(initialTranscript).toEqual(before);
  });
});
