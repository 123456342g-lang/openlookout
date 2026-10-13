# recorder_ext — browse failure signal path

Emits `url` / `nav` / `browser_error` / `form_edit` to `http://127.0.0.1:8765/event`.
`record_win.py` (Windows) writes them into `events.jsonl`.

Install unpacked in Chrome/Edge; grant webNavigation. **Not** a screenshot path.
Until this extension (or equivalent CDP) runs on the PC, sprite **cannot** see ERR_*.
