#!/usr/bin/env python3
"""
OpenLookout multi-agent collaboration board.

Single source of truth for cross-agent work:
  - <repo>/STATUS.md            task board (who owns what: 未认领 / 进行中 / 已完成)
  - <repo>/agents/.locks.json   file locks (which agent may edit which path)

Any agent product that can run Python and git in this repo collaborates by
running this script. Generic by design: stdlib only, no server, no MCP.
Identify yourself with --who <NAME>; the name is whatever identity you choose
for this repo.

Usage:
  python agents/board.py status
  python agents/board.py claim <TASK_ID> --who <NAME> [--files p1,p2]
  python agents/board.py release <TASK_ID> --who <NAME> [--force]
  python agents/board.py lock <PATH>... --who <NAME>
  python agents/board.py unlock <PATH>... --who <NAME>
  python agents/board.py verify <TASK_ID> --run "<CMD>"
  python agents/board.py done <TASK_ID> --who <NAME> --run "<CMD>"

Exit code 0 = ok; 1 = conflict or verification failed (board unchanged).

Windows note: all commands run with the repository root as cwd; use `python`
(Python 3.11+). This script preserves the board file's line endings.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BOARD_DEFAULT = REPO / "STATUS.md"
LOCKS_DEFAULT = REPO / "agents" / ".locks.json"


def die(msg):
    print("board: " + msg, file=sys.stderr)
    sys.exit(1)


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def write_text(path, text):
    Path(path).write_text(text, encoding="utf-8", newline="")


def detect_newline(text):
    return "\r\n" if "\r\n" in text else "\n"


def parse_board(text):
    """Return (lines_with_ends, rows) where each row is (line_index, cells)."""
    lines = text.splitlines(keepends=True)
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("|") and "状态" in ln:
            header_idx = i
            break
    if header_idx is None:
        die("no kanban table (header '| 状态 |') found in board file")
    rows = []
    for j in range(header_idx + 1, len(lines)):
        ln = lines[j].strip()
        if not ln.startswith("|"):
            break
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if all(c in ("", "-", "---") for c in cells):
            continue  # separator row
        rows.append((j, cells))
    return lines, rows


def task_id(cells):
    return cells[1].split(None, 1)[0]


def find_row(rows, tid):
    for row in rows:
        if task_id(row[1]) == tid:
            return row
    return None


def mutate_line(lines, row, new_cells):
    idx, _ = row
    orig = lines[idx]
    suffix = "\r\n" if orig.endswith("\r\n") else ("\n" if orig.endswith("\n") else "")
    lines[idx] = "| " + " | ".join(new_cells) + " |" + suffix


# ---- file locks -------------------------------------------------------------

def load_locks(path):
    p = Path(path)
    if not p.exists():
        return {"files": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"files": {}}


def save_locks(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def norm_path(p):
    return os.path.normpath(p).replace("\\", "/")


def lock_files(paths, who, locks_path):
    data = load_locks(locks_path)
    files = data.setdefault("files", {})
    conflicts = []
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for p in paths:
        key = norm_path(p)
        rec = files.get(key)
        if rec and rec.get("owner") != who:
            conflicts.append((key, rec.get("owner"), rec.get("ts")))
    if conflicts:
        msg = "lock conflict:\n" + "\n".join(
            "  %s locked by %s at %s" % c for c in conflicts
        )
        die(msg)
    for p in paths:
        files[norm_path(p)] = {"owner": who, "ts": now}
    save_locks(locks_path, data)


def unlock_files(paths, who, locks_path):
    data = load_locks(locks_path)
    files = data.setdefault("files", {})
    removed = []
    for p in paths:
        key = norm_path(p)
        rec = files.get(key)
        if rec and rec.get("owner") == who:
            del files[key]
            removed.append(key)
    save_locks(locks_path, data)
    print("unlocked: %s" % (", ".join(removed) if removed else "(none)"))


# ---- commands ---------------------------------------------------------------

def cmd_status(args):
    text = read_text(args.board)
    lines, rows = parse_board(text)
    print("== task board (%s) ==" % args.board)
    first = rows[0][0] - 1  # header line just before first data row
    last = rows[-1][0]
    for ln in lines[first:last + 1]:
        print(ln, end="")
    locks = load_locks(args.locks).get("files", {})
    print("\n== file locks (%d) ==" % len(locks))
    for key, rec in sorted(locks.items()):
        print("  %s -> %s (%s)" % (key, rec.get("owner"), rec.get("ts")))


def cmd_claim(args):
    text = read_text(args.board)
    lines, rows = parse_board(text)
    row = find_row(rows, args.task)
    if row is None:
        die("task %s not found on board" % args.task)
    cells = list(row[1])
    if cells[0] != "未认领":
        die("task %s not claimable: status=%s owner=%s" % (args.task, cells[0], cells[3]))
    cells[0] = "进行中"
    cells[3] = args.who
    mutate_line(lines, row, cells)
    write_text(args.board, "".join(lines))
    if args.files:
        lock_files([f.strip() for f in args.files.split(",") if f.strip()], args.who, args.locks)
    print("claimed %s by %s" % (args.task, args.who))


def cmd_release(args):
    text = read_text(args.board)
    lines, rows = parse_board(text)
    row = find_row(rows, args.task)
    if row is None:
        die("task %s not found on board" % args.task)
    cells = list(row[1])
    owner = cells[3]
    if owner not in (args.who, "—") and not args.force:
        die("task %s owned by %s, not %s (use --force to override)" % (args.task, owner, args.who))
    cells[0] = "未认领"
    cells[3] = "—"
    mutate_line(lines, row, cells)
    write_text(args.board, "".join(lines))
    print("released %s (back to 未认领)" % args.task)


def run_cmd(cmd):
    def dec(b):
        for enc in ("utf-8", "gbk"):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                pass
        return b.decode("utf-8", "replace")
    try:
        p = subprocess.run(cmd, shell=True, cwd=str(REPO), capture_output=True)
        out = dec(p.stdout) + dec(p.stderr)
        return p.returncode, out
    except OSError as e:
        return 1, "failed to run command: %s" % e


def cmd_verify(args):
    rc, out = run_cmd(args.run)
    print(out, end="")
    print("verify: exit %d" % rc)
    sys.exit(0 if rc == 0 else 1)


def cmd_done(args):
    rc, out = run_cmd(args.run)
    print(out, end="")
    if rc != 0:
        die("verification failed (exit %d); task %s stays 进行中" % (rc, args.task))
    text = read_text(args.board)
    nl = detect_newline(text)
    lines, rows = parse_board(text)
    row = find_row(rows, args.task)
    if row is None:
        die("task %s not found on board" % args.task)
    cells = list(row[1])
    owner = cells[3]
    if owner not in (args.who, "—") and not args.force:
        die("task %s owned by %s, not %s (use --force to override)" % (args.task, owner, args.who))
    cells[0] = "已完成"
    mutate_line(lines, row, cells)
    content = "".join(lines)
    if not content.endswith(nl):
        content += nl
    content += "- %s %s：%s 已完成（验收：%s）" % (
        datetime.date.today().isoformat(), args.who, args.task, args.run) + nl
    write_text(args.board, content)
    print("done: %s marked 已完成" % args.task)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--board", default=str(BOARD_DEFAULT), help="task board file (default: STATUS.md)")
    parent.add_argument("--locks", default=str(LOCKS_DEFAULT), help="lock file (default: agents/.locks.json)")

    p = argparse.ArgumentParser(prog="board", description="OpenLookout multi-agent collaboration board")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", parents=[parent], help="show board + file locks")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("claim", parents=[parent], help="claim an unclaimed task")
    sp.add_argument("task")
    sp.add_argument("--who", required=True)
    sp.add_argument("--files", default="", help="comma-separated paths to lock too")
    sp.set_defaults(fn=cmd_claim)

    sp = sub.add_parser("release", parents=[parent], help="return a task to the pool")
    sp.add_argument("task")
    sp.add_argument("--who", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_release)

    sp = sub.add_parser("lock", parents=[parent], help="lock file paths")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--who", required=True)
    sp.set_defaults(fn=lambda a: lock_files(a.paths, a.who, a.locks))

    sp = sub.add_parser("unlock", parents=[parent], help="unlock file paths owned by you")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--who", required=True)
    sp.set_defaults(fn=lambda a: unlock_files(a.paths, a.who, a.locks))

    sp = sub.add_parser("verify", parents=[parent], help="run acceptance command only")
    sp.add_argument("task")
    sp.add_argument("--run", required=True)
    sp.set_defaults(fn=cmd_verify)

    sp = sub.add_parser("done", parents=[parent], help="run acceptance command; on success mark task 已完成")
    sp.add_argument("task")
    sp.add_argument("--who", required=True)
    sp.add_argument("--run", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_done)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
