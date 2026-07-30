# Memory Repair Process Rules

These rules govern how memory repair operations are executed. They are
not suggestions — they are the protocol that prevents execution drift.

## 1. Show, don't execute

Every repair operation must:
1. Enumerate what it WILL change (files, columns, rows, memory entries)
2. Explain WHY each change is needed (root cause, not symptom)
3. Ask for approval before modifying anything

If a change cannot be enumerated in a short report, it needs more
investigation before it runs.

## 2. Re-show after matcher change

If the deletion or matching criteria change after an initial dry run,
the new set of targets must be re-shown to the user with a clear
explanation of what changed and why.

Example: a CSV matcher that was meant to flag 14 rows might pick up
7 more if a column name changes or a regex broadens. The new count
must be reported before execution.

Reason: the user approved based on the first number. A second run
under different criteria is a different approval.

## 3. Verify after every write

After any write operation completes:
- Verify the expected change occurred
- Check that nothing else was affected
- Report the before/after state

A write that "succeeded" but produced the wrong count is still a
failure.

## 4. Document the decision

If you skip something (e.g., skip deduping a table because it's not
ready), note WHY in the report. The reason may be "not enough info"
or "too risky now" — either way it should be documented so the
question gets revisited later instead of forgotten.

## 5. Bleeding edge only — no exceptions

These rules prevent "it worked last time" from becoming "it corrupted
the whole system this time." Every memory repair runs against a backup
or can be rolled back to one. No exceptions.

## 6. Merge vs dedupe distinction

- **Dedupe**: remove exact-duplicate rows. Safe — folding counts is
  benign bookkeeping.
- **Semantic merge**: collapse rows that are conceptually the same
  but differ in wording. Lossy — the merge picks ONE string as
  canonical and discards the rest.

Semantic merges require:
a) A dry run showing which rows merge
b) The surviving text for each cluster
c) A reason for the choice (highest count? most recent?)
d) Approval to proceed

If the selection rule is "highest access_count" and the generic
string has a higher count than the specific one, say so. The user
may choose the most-specific string instead.

## 7. The "dark amber" rule

Two preferences that overlap in surface space but target different
things are NOT the same fact. Examples:
- "I prefer dark amber terminal themes." — terminal setting
- "User likes dark mode" — general UI toggle
- "User prefers dark theme" — possibly a subset of either

Do not merge these under a 0.85 similarity threshold. Each may be
relevant in different contexts. The cost of a missed merge is a
few extra rows; the cost of a wrong merge is losing detail
permanently.

## 8. Process completion report

After any repair sequence completes:
- Starting counts (by table/collection)
- What was purged and why (each category)
- What merged (if applicable) and survivor text
- Final counts
- Validation method
- Where the backup lives
- What was deferred and why

## 9. Backup verification

A backup is not verified until it has been used to restore a small
sample and confirm it's the right data. "Verified by diff" is not
backing up a bag of rocks and calling it a day.

## 10. Approval is required for each phase

Each phase gets its own approval gate:
1. Purge (delete junk rows)
2. Dedupe (fold duplicates)
3. Re-embed (recompute vectors)
4. Merge (semantic collapse)
5. Rebuild index (if applicable)

One approval per phase, not "approve everything."

## 11. Memory health report

After repair completes, run `memory_health.py --strict` and include
the report in the completion summary. If it fails, the repair is
incomplete.
