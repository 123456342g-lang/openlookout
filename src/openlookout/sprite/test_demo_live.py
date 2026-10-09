import json, os, re, subprocess, sys
from pathlib import Path
import pytest
from sprite.demo_live import stage_demo, common
from sprite.demo_live.eat_memory import Eater, CHUNK_MB

DL = Path(__file__).resolve().parent / "demo_live"


def test_stage_check_and_reset_safety(tmp_path):
    root = tmp_path / "sbx" / "demo"; man = stage_demo.stage(root)
    assert len(man["safe"]) == 13 and len(man["risky"]) == 2 and len(man["traps"]) == 11
    c = stage_demo.check(root); assert c["all_restored"] and c["traps_intact"] == 11
    (root / "Temp" / "tmp0.tmp").unlink(); assert not stage_demo.check(root)["all_restored"]
    stage_demo.stage(root); assert stage_demo.check(root)["all_restored"]                 # 重新铺设
    other = tmp_path / "not_sandbox"; other.mkdir(); (other / "precious.txt").write_text("x")
    with pytest.raises(SystemExit): stage_demo.stage(other)                               # 没有标记文件的目录：拒绝，不删
    assert (other / "precious.txt").exists()


def test_eater_never_goes_below_floor():
    avail = [8000.0]
    e = Eater(leave_gb=0.2, mem=lambda: (16000.0, avail[0]))                              # 参数要求留 0.2GB，但硬下限是 1.5GB
    assert e.leave == common.EAT_FLOOR_GB
    n = 0
    while e.step() and n < 1000: avail[0] -= CHUNK_MB; n += 1                             # 假装每吃一块可用内存就减少一块
    assert avail[0] / 1024 >= common.EAT_FLOOR_GB - 1e-9 and e.held_mb > 0
    e.release(); assert e.held_mb == 0 and not e.step()


def test_eater_stops_at_requested_mb():
    e = Eater(1.5, mb=128, mem=lambda: (32000.0, 30000.0)); n = 0
    while e.step(): n += 1
    assert e.held_mb == 128; e.release()


def test_thresholds_leave_room_on_small_and_large_machines():
    for total in (4096, 8192, 16384, 32768, 65536):
        dc = dict(mem_warn=0.20, mem_warn_gb=None)
        w, tgt = common.warn_gb(total, dc), common.eat_target_avail_gb(total, dc)
        assert tgt >= common.EAT_FLOOR_GB and tgt < w, (total, w, tgt)                     # 能触发，且始终留 ≥1.5GB


def test_no_kill_anywhere_in_process_code():
    for f in [DL.parent / "procctl.py", *DL.glob("*.py"), *DL.glob("*.bat")]:
        t = f.read_text("utf-8")
        assert not re.search(r"taskkill|TerminateProcess|\.terminate\(|SIGKILL|os\.kill\([^)]*SIGTERM", t), f.name        # 演示代码里没有结束进程的调用
    assert "eat_memory" in (DL / "trigger_memory_explosion.bat").read_text("utf-8")


def test_bat_files_are_crlf_utf8_and_point_only_to_sandbox_defaults():
    for f in DL.glob("*.bat"):
        b = f.read_bytes(); assert b"\r\n" in b and b"\n" not in b.replace(b"\r\n", b""), f.name
        t = b.decode("utf-8")
        for m in re.findall(r"[A-Z]:\\[^\s\"%]*", t): assert m.startswith("E:\\OpenLookout\\"), (f.name, m)


def test_eat_memory_cli_smoke():
    r = subprocess.run([sys.executable, "-m", "sprite.demo_live.eat_memory", "--no-gui", "--mb", "128", "--timeout", "2"], cwd=DL.parent.parent, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "下限 1.5GB" in r.stdout
