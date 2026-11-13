# Reconnectable questions, editable conditions and bounded reading

## Background question lifecycle

The browser saves its question/assistant placeholder before POST `/api/ask/start`. A request ID and exact chat/message/question targets identify the job. Repeating the same start is idempotent; reusing the ID for a different payload is rejected. At most eight active jobs are accepted, with two local workers and the existing single interactive model lane.

The request body/history lives only in the worker while executing. Final answers are committed to the existing `conversations.json`; there is no second durable answer store. Client snapshots cannot replace server-owned question fields, and request versions prevent stale responses from rewinding the browser. `/api/ask/job` reconnects to a specific target and returns its progress/result. Closing or reloading a browser does not cancel the worker. Actual application shutdown cancels its jobs, and unfinished saved jobs become retryable after restart without automatic model resubmission. Rechecks retain a previous completed answer on failure.

Company-model confirmation pauses the background task, preserves the existing review flow, and waits for confirmation of the same destination fingerprint. Cancellation remains scoped to the question's worker. Deleted targets are never recreated by a late result; source existence/authorization is checked before committing an answer.

## Conditions

Each inferred condition is keyed to its original user message. Edits are stored in `contextEdits`; removal uses the existing ignored-ID list. The original chat text is unchanged. Both retained conditions and recent model history use the edited statement, and removed conditions are excluded from recent history. Clear-all still works. Permanent deletion removes orphan condition edits and maintains the reset boundary.

## Additional reading

Long indexed sources receive a bounded local second pass: at most three source records, body-ranked additional sections, and neighboring chunks. The combined evidence is limited to 20 passages / 24,000 characters. Source IDs and origins are built from the archive, not model-generated paths. Before additional reading, the same company/source authorization gate applies.

For anchored PDF passages, at most two adjacent pages can be read from the original through the existing PDFium ownership layer, with text-only extraction and source-file change checks. This does not extend saved PDF selections or regenerate summaries. Scans without text report the OCR limitation rather than silently triggering OCR. Progress reports “reading relevant sections and neighboring content”, and timing details show the number of added passages.

## Suspend / reconnect

Existing visibility, focus and pageshow refresh remains. A wall-clock gap monitor also triggers a server-state refresh after a gap of at least 15 seconds. This covers sleep, suspended tabs and throttled browsers without submitting another question. The monitor records only gap counts/durations in browser memory, with no document titles or contents.

`check_question_recovery_ui.py` exercises real local API workers while closing a page, opening a fresh browser, editing/removing conditions, refreshing during a request, and injecting a clock gap. A clock-gap test is a simulation, not proof of real OS sleep/wake. Actual sleep/wake requires target-machine user participation. The independent conversation-validation workflow runs source/unit/browser/native-window checks on Windows and Linux without building or publishing a release.

## Checks

- Full unit suite and chat JavaScript regression.
- `tests/test_question_jobs.py`: durable completion, restart recovery, stale snapshots, idempotency, cancellation, deletion fencing and company confirmation.
- `tests/test_evidence_context.py`: late sections, character/count bounds, short-source fast path and an initially unindexed adjacent page of a synthetic 51 MB PDF.
- `scripts/check_question_recovery_ui.py` plus existing controls, citations and full-chat browser regressions.
- Synthetic live-model evaluation uses `scripts/evaluate_library_chat.py`; no real library records are exported to test reports.

## Additional findings

The expanded live Codex matrix exposed a catalog query issue: multiple Chinese history synonyms were sometimes emitted as one space-separated query, causing an impossible AND match. If the original catalog is empty, shared subject terms are now considered with a scope notice; existing nonempty exact matches are preserved. Actual emitted query strings and a bounded history-suffix fallback are covered by regression tests.

The first independent Linux run passed. The first Windows run identified an unclosed SQLite reader in the no-GUI convergence test; the test now explicitly closes that connection instead of suppressing cleanup errors. Native/window and browser verification continues in the dedicated validation workflow. Claude live evaluation was attempted but its account is currently paused, so no Claude quality pass is claimed.
