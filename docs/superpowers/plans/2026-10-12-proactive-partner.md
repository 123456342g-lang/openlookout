# Proactive Partner Lifecycle Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. User approved inline implementation in the existing workspace; do not commit, branch, reset, or replay paid models.

**Goal:** Preserve and advance evidenced unfinished work independently of speech and screen changes, then assess actual results before completion.

**Architecture:** VISTA keeps semantic and visual memory. Agenda remains the sole durable execution record; the existing ContinuationTracker deduplicates concrete wake opportunities. Companion speech and work summaries are exposed separately, while actual tool requests and independent verification receipts survive restart.

**Tech Stack:** Python 3.11, pytest, existing VISTA TaskRuntime and desktop tool contracts.

**Spec:** `docs/superpowers/specs/2026-10-12-proactive-partner-design.md`

## Global Constraints

- Preserve all existing permission, rollback, stale-screen and tool-effect checks.
- Do not build another visual memory, user profile, queue or asynchronous execution framework.
- Work within the existing dirty workspace; use apply_patch for every edit.
- Use isolated fake tools and local pytest, without paid model calls or private log bodies.
- This slice proves lifecycle continuity, not opportunity discovery or strategic intelligence.

### Task 1: Work and speech continuity

**Files:** `src/openlookout/vista/benchmarks/desktop/{agenda,session,brain,test_partner_lifecycle}.py`

**Interfaces:** Agenda exposes concrete continuation steps for ready/verify goals whose dependencies are done. ContinuationTracker.pending(decision, revision, agenda=None) selects an unconsumed step across all goals; existing callers retain their signature. The selected step is available as tracker.step. Companion/current expose speech and work separately.

- [ ] Write a failing quiet/ready test and unchanged-screen lifecycle using real DesktopSession and Agenda with isolated tools.
- [ ] Run `D:/python3.11/python.exe -m pytest vista/benchmarks/desktop/test_partner_lifecycle.py -q` from `src/openlookout`; observe failures caused by missing work continuation.
- [ ] Add concrete Agenda steps and extend the existing tracker, filtering terminal/blocked goals and duplicate stale speech steps. Quiet defaults to the actual executable step when one exists; speech does not update Agenda.
- [ ] Main loop uses the tracker's chosen work step rather than the latest bubble; feedback rounds do not consume work that was not attempted. Record delivery only after the offered turn and preserve revisions produced within it.
- [ ] Verify repeated quiet without tool progress gets no repeated autonomous wake; other unconsumed goals still get their turn.

### Task 2: Actual receipts and restart safety

**Files:** `src/openlookout/vista/benchmarks/desktop/{agenda,session,test_partner_lifecycle}.py`

**Interfaces:** Goal.request persists the claimed tool, actual arguments, phase, expected result and mutation flag. Goal.action_result retains the action receipt when last_result becomes independent verification. Goal.assessment stores the completion explanation. Existing agenda files load through dataclass defaults.

- [ ] Add failing tests for actual arguments differing from permitted planned deliverable content, persisted assessment, and restart after an uncertain action.
- [ ] Run the focused test file and confirm receipt assertions fail on current code.
- [ ] Persist actual requests at claim time and include request/expected in result receipts. Keep mutation recovery in verify, never replay the original request.
- [ ] Pass actual handler arguments into record; keep existing result_id and independent read-only verification requirements.
- [ ] Run lifecycle and existing agenda/history/conversation tests.

### Task 3: Verification and handoff

**Files:** `STATUS.md`, `TASKS.md`, this plan.

- [ ] Run `D:/python3.11/python.exe -m pytest vista/benchmarks/desktop sprite/proactive -q`.
- [ ] Review only the changed diff and request the independent agent's read-only review.
- [ ] Check supervisor/current metadata without printing private content or credentials; distinguish local regressions from real product evidence.
- [ ] Record the verified behavior and remaining gaps in both boards; leave changes uncommitted.
