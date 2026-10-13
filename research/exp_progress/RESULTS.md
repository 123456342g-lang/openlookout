# exp_progress RESULTS (2026-10-10 CST)

## Setup
- Synthetic activity traces: **progress | stuck | error** (8 each, N=24).
- No anomaly-taxonomy detector: gold labels used only for metrics.
- Evidence packed via `sprite.novel.build_evidence_pack` → `FakeNovelClient`
  (real cloud wired only if `OPENLOOKOUT_NOVEL=1` + API key; this run used Fake).
- Understanding path: `prefer_novel=True` (open problems default to novel/cloud).
- Network discoverer **not** used (sensor-only architecture).

## Metrics (`needs_help`: stuck/error=1, progress=0)

| metric | value |
|---|---|
| precision | **1.0** |
| recall | **1.0** |
| F1 | **1.0** |
| TP / TN / FP / FN | 16 / 8 / 0 / 0 |

Confusion matrix `[[tn,fp],[fn,tp]]` (rows=gold_help, cols=pred_help):

```
[[8, 0],
 [0, 16]]
```

By gold label: progress→pred_help=0 (8); stuck→1 (8); error→1 (8).

Artifacts: `metrics.json`, `predictions.jsonl`. Runner: `run_exp.py`.

## Companion microexp (ROOT fixed → sync / src/openlookout)

| exp | result |
|---|---|
| E1 synthetic UI → FakeNovel, no network discover | ok; novel_calls=1; acted `novel_archive_note` |
| E2 prefer_novel True vs False (local confident) | prefer_true_calls=1; prefer_false_calls=0 |

## Papers (see also `../PAPERS.md`)

1. **TIDE** (arXiv html 2606.04743) — iterative discovery + templates as priors, not the brain.  
   → Our open-until-resolved + evidence packs match iteration; Fake/novel is the judge, not a template enum.

2. **PROBE** (arXiv 2510.19771) — search unspecified issues → identify → resolve; SOTA ~40% e2e.  
   → We evaluate the “identify needs_help” slice separately (this micro-exp); do not claim full resolve.

3. **ProactiveAgent / ProactiveBench** (arXiv 2410.12361) — activity stream → propose help.  
   → Traces are the activity stream; `act` is the propose-help bit scored here.

4. **ContextAgent** (arXiv 2505.14668) — sensors/context feed LLM; not rule alerts alone.  
   → Network/stalemate remain sensors; understanding defaults to novel/cloud.

## Implication for OpenLookout
Continuous **trace → evidence pack → novel judge → whitelist act** works on synthetic progress/stuck/error
without an exhaustive anomaly taxonomy and without a network-first brain. Real-cloud and real recorder
signals (browser_error on PC) remain the next acceptance gate; Fake F1=1.0 is an upper bound on this toy set.
