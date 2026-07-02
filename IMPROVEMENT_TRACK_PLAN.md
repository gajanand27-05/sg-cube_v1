# SG_CUBE — Track Plans

## Track 1 — Intelligence Refinement

**Goal:** Make SG_CUBE think better using the existing architecture. No new agents or major architectural changes.

| Phase | Change | Files | Effort | Priority |
|---|---|---|---|---|
| **T1-1** | Fix 3 bugs (guardian arg mismatch, ConversationContext.session_id, LTM importance filter) | 3 files | +3/-1 lines | **P0** |
| **T1-2** | Planner retry on JSON parse failure | 1 file | ~15 lines | **P1** |
| **T1-3** | Planner prompt quality (remove 50-cap, add tags + security) | 1 file | ~5 lines | **P1** |
| **T1-4** | Lower planner temperature 0.2 → 0.1 | 1 file | 1 char | **P2** |
| **T1-5** | Enable follow-up mode (_FOLLOWUP_WINDOW_S, lower threshold) | 1 file | 2 constants | **P2** |

Deferred (not in current sprint):
- T1-6 Memory scoring alignment (LTM.search vs MemoryManager.recall use different formulas)

**Total T1 effort**: ~25 lines across 5 files.

---

## Track 2 — Productivity Integrations

**Goal:** Expand what SG_CUBE can do by adding real-world capabilities using existing @tool pattern. No new dependencies (stdlib + already-installed packages).

| Phase | Change | Files | Effort | Priority |
|---|---|---|---|---|
| **T2-1** | `run_command` — subprocess wrapper, CAUTION | 2 files (+test) | ~30 lines | **P1** |
| **T2-2** | `read_file`, `edit_file`, `insert_lines`, `write_file` — file editing | 1 file | ~40 lines | **P1** |
| **T2-3** | `read_webpage` — requests + BeautifulSoup, plain text extract | 1 file | ~15 lines | **P1** |

Parked (add only if daily dogfooding justifies):
- T2-4 Git helper tools (git_status, git_stage, git_commit, git_diff)
- T2-5 VS Code launch & navigate (open_in_vscode, code --goto)

**Total T2 effort**: ~85 lines across 4 files.

---

## Execution order

1. **T1-1** (fix 3 bugs — unblocks everything below)
2. **T1-2** (planner now survives bad LLM output)
3. **T1-3** (planner sees all tools with richer signal)
4. **T2-1** (terminal — highest leverage new capability)
5. **T2-2** (file editing — unlocks real work)
6. **T2-3** (webpage reading — rounds out browser)
7. **T1-4 + T1-5** (trivial, slot anywhere)
8. Run full `test_all_phases.py`, smoke-test new tools
