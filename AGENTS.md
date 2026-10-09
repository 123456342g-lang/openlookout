# Repository Guidelines

## Project Structure & Module Organization

The main Python project lives in `src/openlookout/`. Its `lookout/` package contains detection, privacy filtering, artifact generation, and the V1 entry point, `v1.py`. Read `src/openlookout/V1.md` before changing product behavior. `backfill_win/`, `recorder_win/`, and `recorder/` collect historical or live activity; `recorder/extension/` contains the browser extension. Root-level `record_win.py` and `backfill_win/backfill_win.py` are additional Windows entry points; check which copy you are changing.

Tests live beside features and under component `tests/` directories. `sim/`, `sim_home/`, and `ground_truth/` support simulations; `demo/` holds example reports and prepared artifacts. `real_data/` contains dataset conversion tools. Local capture output belongs in `data/` or an explicitly selected output directory.

## Build, Test, and Development Commands

Use Python 3.11 for compatibility with the Windows backfill tool. There is no configured build step. Install the main pipeline dependency with `python -m pip install openpyxl`.

From the repository root:

- `python backfill_win/backfill_win.py --plan`: preview collection locations.
- `python record_win.py --seconds 600`: record ten minutes of Windows activity.

Run pipeline and test commands from `src/openlookout/`:

- `python -m lookout.v1 --capture ../../data/backfill --out runs/local --no-llm`: analyze an existing capture without cloud model calls.
- `python -m lookout.test_surprise`: run the standalone surprise-gate checks.
- `python -m unittest discover -s opportunities/tests -v`: run opportunity-engine tests.
- `python backfill_win/tests/test_backfill.py`: run fixture-based backfill checks; review its fixed `/tmp/bf_fx` workspace before execution.

## Coding Style & Naming Conventions

Follow surrounding Python code: four-space indentation, `snake_case` modules and functions, and uppercase constants. Preserve UTF-8 text and existing event-schema field names. Keep changes focused. No formatter or linter configuration is present.

## Testing Guidelines

Tests use `unittest` and standalone assertion scripts. Name tests `test_*.py` and test functions `test_*`. Run the relevant component suite; no coverage threshold is configured. Use synthetic fixtures to verify detection, output schemas, privacy redaction, and read-only collection behavior.

## Commit & Pull Request Guidelines

This checkout has no Git metadata, so commit conventions cannot be verified. Use concise imperative subjects. PRs should explain behavior changes, reference relevant issues, and list validation commands and results. Include screenshots for report or inbox layout changes.

## Security & Configuration

Keep raw activity, credentials, `.env` files, and private captures local. Preserve URL redaction and outbound-data auditing. Never attach private datasets to PRs; use synthetic examples.
