# SG_CUBE — Development Mandates

## Testing & Validation
- **Mandatory Testing:** Every code change MUST be accompanied by a corresponding test or a verification step.
- **Phase Validation:** After completing each phase or significant feature, you must perform autonomous end-to-end testing to verify the entire system remains functional.
- **Empirical Reproduction:** For bug fixes, always reproduce the failure with a script or test case before applying the fix.
- **Regression Testing:** After making changes, run existing related tests to ensure no regressions were introduced.

## Engineering Standards
- **Quality & Neatness:** Build thoroughly and neatly. Adhere to idiomatic Python style, maintain clean folder structures, and ensure all changes are well-documented and consistent with the existing codebase.
- **Surgical Edits:** Prefer precise, targeted changes over broad refactors unless explicitly requested.
- **Local First:** Maintain the "Local-First" architecture. Do not introduce dependencies that require an internet connection for core functionality (STT, LLM, TTS, Logic).
- **Security:** Never log or commit secrets, API keys, or personal credentials.

## Source Control
- **Automatic Commit & Push:** After every successful verification/testing cycle, immediately commit and push the changes to GitHub.
