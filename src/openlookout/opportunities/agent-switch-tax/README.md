# agent-switch-tax

Measure the **cold-start knowledge tax** of switching coding agents on a real project.

## Insight

You keep paying setup / subscription / switching cost across OpenCode, Codex, CC Switch, … as if the scarce resource is model quality. The unstated problem: **each cold agent re-loses the project's durable facts** (constraints, invariants, module roles, past decisions). Multi-provider switchers move models; they do not move institutional memory.

## Usage

```bash
python3 switch_tax.py --project ../.. --profile ../../demo_private/profile_abstract.json --out /tmp/switch_tax_out
python3 -m unittest discover -s tests -v
```

Outputs: `ledger.json`, `ledger.md`, `metrics.json`, `report.md`.

Stdlib only. No network. Does not read capture raw events.
