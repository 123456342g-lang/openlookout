# Autonomous Continuity Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline with independent requesting-code-review checkpoints. No Git commit is authorized.

**Goal:** Repair lost proactive continuation and history exploration in the existing sprite.

**Architecture:** Keep VISTA tools and semantic notes; fix callable continuation identity, snapshot lifecycle and opportunity probe invalidation.

**Tech Stack:** Python 3.11, VISTA TaskRuntime, pytest, Anthropic-compatible configured provider.

**Spec:** docs/superpowers/specs/2026-10-12-autonomous-continuity-design.md

## Global Constraints

- No user file deletion, permission bypass, user process termination or real cleanup by Codex.
- No injected actual homework title, answer or deadline.
- No new visual memory, domain whitelist, Git commits or unrelated refactor.

### Task 1: Callable continuation

Files: brain.py and test_historyfacts.py in src/openlookout/vista/benchmarks/desktop/.

- [x] Add failing tracker test: same tool with offset15/30 proceeds, changed prose for the same tool does not replay.
- [x] Run `python -m pytest vista/benchmarks/desktop/test_historyfacts.py -q` from src/openlookout.
- [x] Implement key from tool/arguments; preserve legacy goal/action key when absent. Serialize complete selected step into continuation public text.
- [x] Verify tracker and ordinary dialogue tests, preserving fresh feedback/scene validation.

### Task 2: History lifecycle and opportunities

Files: historyfacts.py, brain.py, test_historyfacts.py, test_natural_conversation.py.

- [x] Add failing unchanged Feed cache test, plus model request regression for changed history after first completed probe.
- [x] Run tests to observe old-cache eviction and missing probe failures.
- [x] Stage candidate snapshot, publish on changed collected content or evicted cursor; retain valid original cursor otherwise. Record the context actually covered by a probe, allow newly provided context to reawaken comparison; do not preempt direct message or explicit continuation.
- [x] Run desktop/proactive regression; inspect actual runtime tool receipts after hot update.

### Task 3: Real-model review and handoff

Files: replay_openworld.py, test_openworld_replay.py and documentation.

- [x] Add isolated paged-history replay so relevant source appears after initial page and no hidden error is stated.
- [x] Run real model problem and clean control; require generated rows, successful independent full read and done goal state.
- [x] Dispatch independent read-only reviewer with exact file scope and goals; address demonstrated correctness issues.
- [x] If Qodo login succeeds, attach self-contained context for scoped review. Otherwise report exact readiness limitation: CLI installed, whoami returns not_logged_in, no Qodo review performed.
- [x] Update TASKS/STATUS and report measured behavior without claiming arbitrary complex work is solved.

## Measured Outcomes

Strict paging rejects an offset without a snapshot; the replay no longer supplies a missing cursor behind the model's back. Purchase problem: 105.8s, generated and independently read a correct difference table. After resolving contradictory reporting instructions, clean control: 41.5s, no message or duplicate deliverable. Measurement problem: 77.4s, generated and independently read a correct unit-conversion table. These are isolated configured-model scenarios, not proof of discovering the user's actual next homework.
