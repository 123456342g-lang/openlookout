# Proactive observe — paper notes (2026-10-10)

Goal: notice unspecified problems without an exhaustive anomaly taxonomy.

## Closest matches

1. **TIDE** — Template-guided Iterative Discovery and rEsolution  
   https://arxiv.org/html/2606.04743  
   Frame: many hidden problems coexist; number unknown. Iterative discovery (batch per round, condition on already-found) + thought templates distilled from solved cases. Output must ground in evidence and propose resolution.  
   **Takeaway for us:** don’t one-shot “list all problems”; iterate; templates are priors not the brain.

2. **PROBE** — Beyond Reactivity: Measuring Proactive Problem Solving  
   https://arxiv.org/html/2510.19771  
   Pipeline: search unspecified issues → identify bottlenecks → resolve. Even SOTA ~40% end-to-end.  
   **Takeaway:** evaluate search/identify/resolve separately; hard benchmark — expect failure modes.

3. **Proactive Agent** (THU) — ProactiveBench  
   https://arxiv.org/pdf/2410.12361  
   Predict tasks from activity streams; reward model for accept/reject.  
   **Takeaway:** activity stream → propose help; need human preference signal.

4. **ContextAgent** — open-world sensory perceptions  
   https://arxiv.org/html/2505.14668  
   Proactive from sensors/context not only UI rules.  
   **Takeaway:** sensors feed LLM; not rule alerts alone.

## Design implication (OpenLookout)
- Continuous **trace stream** (focus/UI progress), not anomaly enum.
- Cloud judge: “is the user progressing on an intent?” → problem + reversible act.
- Iterate while open (aligns open-until-resolved + TIDE iteration).
- Micro-experiment: synthetic traces (progress vs stuck vs error) → Fake/Real novel judge → precision/recall of “needs help”.

