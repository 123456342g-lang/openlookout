"""压力检测：由状态变化驱动（阈值 + 变化速率 + 迟滞），不是定时任务。只在“级别上升”时产生事件（边沿）；同一级别持续不重复上报。
未解除的持续状态由 Engine.open 挂起并每轮推进，检测器不必每轮重报。poll 只是读取状态的方式，决策来自状态变化。"""
from __future__ import annotations
from dataclasses import dataclass

LEVELS = {0: "ok", 1: "warn", 2: "critical"}


@dataclass
class Pressure:
    kind: str            # mem | disk
    level: int
    target: str          # 内存或盘符
    evidence: str
    need: float          # 需要释放：mem 为 MB，disk 为 GB（回到安全线）


class PressureDetector:
    def __init__(self, mem_warn=0.20, mem_crit=0.10, disk_warn=0.12, disk_crit=0.05, disk_crit_gb=5, fall_mb_per_min=500, hyst=0.03):
        self.p = dict(mem_warn=mem_warn, mem_crit=mem_crit, disk_warn=disk_warn, disk_crit=disk_crit, disk_crit_gb=disk_crit_gb, fall=fall_mb_per_min, hyst=hyst)
        self.level = {}; self.prev = None

    def _lv(self, key, new, frac_ok_margin):
        old = self.level.get(key, 0)
        if new < old and frac_ok_margin < self.p["hyst"]: new = old       # 迟滞：没明显回落就保持原级别（但不重复报）
        self.level[key] = new
        return old, new

    def update(self, s) -> list:
        out = []
        frac = s.mem_avail_mb / s.mem_total_mb
        lv = 2 if frac < self.p["mem_crit"] else 1 if frac < self.p["mem_warn"] else 0
        rate = 0.0
        if self.prev and s.t > self.prev.t:
            rate = (self.prev.mem_avail_mb - s.mem_avail_mb) / ((s.t - self.prev.t) / 60)
            if lv == 0 and frac < 0.35 and rate > self.p["fall"]: lv = 1         # 还没到阈值，但在快速下降
        old, new = self._lv("mem", lv, frac - self.p["mem_warn"])
        if new > old:
            tgt = self.p["mem_warn"] + 0.05
            out.append(Pressure("mem", new, "内存", f"可用内存 {s.mem_avail_mb/1024:.1f}/{s.mem_total_mb/1024:.1f} GB（{frac:.0%}）" + (f"，每分钟下降 {rate:.0f} MB" if rate > self.p["fall"] else ""),
                                max(0.0, tgt * s.mem_total_mb - s.mem_avail_mb)))
        for d, (tot, free) in s.disks.items():
            f = free / tot
            lv = 2 if (f < self.p["disk_crit"] or free < self.p["disk_crit_gb"]) else 1 if f < self.p["disk_warn"] else 0
            old, new = self._lv(("disk", d), lv, f - self.p["disk_warn"])
            if new > old:
                out.append(Pressure("disk", new, d, f"{d} 剩余 {free:.1f}/{tot:.0f} GB（{f:.0%}）", max(0.0, (self.p["disk_warn"] + 0.03) * tot - free)))
        self.prev = s
        return out
