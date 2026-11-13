# Conversation reliability and responsiveness

This work uses synthetic reproductions of reported conversations, not private library exports. No release tag is created until the user tries the source version.

1. **Regression cases**: `tests/fixtures/conversation_regressions.json` covers schedule questions, declarative clarification, weekday/relative-date follow-ups, changing person/topic and complete record listing. `test_conversation_regressions.py` checks retrieved/cited identities, call budgets, long-document fallback and source changes using a controlled model. This verifies the pipeline contract, not the prose quality of every external model.
2. **Context**: preserve the last sourced topic alongside the recent five turns after general chat; explicit conditions remain bound to their source IDs. Conditions and old answers from another source are excluded from answer context. Removed-source history is excluded before planning. New-topic planning remains enabled, and current user corrections take priority in the answering prompt.
3. **Follow-up speed**: bounded, unambiguous day/time schedule follow-ups skip query planning. Large documents or unavailable evidence fall back to normal planning. Prepared images are reused for up to five minutes, with eight entries and a 24 MB total bound. Source revision, original-file metadata, selected origins and vision capability invalidate reuse. The actual image is still supplied to each model answer; Check again bypasses reuse.
4. **Answer style**: lead with the answer, give only necessary scope/assumptions, distinguish source facts from user conditions and inference, and retain citations. External model compliance still needs live review.
5. **Cancellation/retry**: a per-request event stops the corresponding CLI/API worker or queued request. It does not cancel summary tasks. Pre-start cancellation blocks a late request. Partial output is never cached as an answer. Failed/stopped requests can retry, and failed rechecks preserve completed text/references. Pending progress remains transient.
6. **Background convergence**: success, timeout and restart recovery are checked by reading SQLite with no HTTP server or GUI. Existing visibility/focus/pageshow refresh remains in place. Actual machine sleep/wake is a manual check, not simulated as an automated OS test.
7. **Source consistency**: citations carry source revisions; dashboard metadata flags updates and trash without retaining a second body copy. Removed sources are not reopened through stale original links. Permanent deletion continues to remove related chat messages per the existing deletion policy. Answer/image cache validity includes archive/file changes.
8. **Setup**: settings automatically detect configured APIs or discovered CLIs locally and explain next steps, without claiming login/connectivity success. Explicit Test model connection verifies the selected configuration. Keyword search needs no downloaded model; answering requires a CLI/API service, while optional semantic search needs a separately configured embedding service. The guide applies to Windows, Mac and Linux.

## Validation

- `python -m unittest discover -s tests`
- `node --test tests/test_chat_ui.cjs`
- `python scripts/check_conversation_controls_ui.py`: real synthetic HTTP model/API subprocess; cancellation releases the lane, retry completes, failed recheck preserves answer, updated/trashed citations, bilingual setup guide.
- Existing chat, citation and language browser regressions.
- Live model evaluation is opt-in: `.venv/bin/python scripts/evaluate_library_chat.py --run-model --backend codex --case weekday_ellipsis`. It uses an isolated synthetic library and writes `/tmp/stellar-chat-evaluation.json`, recording timings and topic citations. Review the answer for correct date/time, ownership, assumption scope, citations and concise phrasing; a cited-topic match alone is not a correctness score.
- Before release, manually try source with the existing library. On Windows verify discovery after CLI installation/login and restart, explicit connection testing, and a library follow-up. Verify actual sleep/wake on the target machine. These platform checks are not implied by a Mac-only test pass.

## Local results (2026-11-13)

- Full suite: 364 tests, 10 platform-dependent skips; chat JS, compact source-link UI, complete chat improvements UI, bilingual UI and new conversation-controls browser checks passed.
- Live Codex on two synthetic cases: weekday follow-up used one model call in 11.585 s; a new Roman-history topic used planning plus answering in 19.289 s. Both cited the intended source, and manual review found no schedule-condition leakage into the history answer. These are individual observations, not a latency guarantee or a comparison against the same question before this change.
- Windows/Linux execution is deferred to their CI jobs; the new controls browser check is included in both workflows. Actual machine sleep/wake remains a manual target-machine verification.
