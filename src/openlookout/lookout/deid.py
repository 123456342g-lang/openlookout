"""c 段的确定性脱敏（本机原型没有跑本地小模型：机器共享内存只剩约 3GB，见报告）。
规则：人名 → ⟨人名k⟩；文件名/路径 → 表A/文档组D 之类代号；长数字串 → ⟨编号⟩；邮箱/手机号/证件号 → 占位符。
最后有一道"出站审计"：任何真实人名、文件名、≥6 位数字出现在出站文本里，就拒绝发送。"""
import re
from .common import read_table, read_text_any, watched_files

NAME_COL = re.compile(r"(人|成员|姓名|领用|操作|负责)")

def collect_names(meta):
    names = set(meta.get("user_aliases", []))
    for p in watched_files(meta):
        try:
            if p.suffix in (".xlsx", ".csv"):
                h, rows = read_table(p)
                for i, c in enumerate(h):
                    if NAME_COL.search(c):
                        names |= {str(r[i]) for r in rows if r[i] and 2 <= len(str(r[i])) <= 4}
                if p.suffix == ".xlsx":   # 真实表格常常一周一个工作表，只看活动表会漏掉其它表里的名字
                    import openpyxl
                    for ws in openpyxl.load_workbook(p, read_only=True, data_only=True).worksheets:
                        hdr = None
                        for r in ws.iter_rows(max_row=400, values_only=True):
                            if hdr is None:
                                if any(isinstance(c, str) and NAME_COL.search(c) for c in r): hdr = [str(c or "") for c in r]
                                continue
                            for i, c in enumerate(hdr):
                                if NAME_COL.search(c) and i < len(r) and isinstance(r[i], str) and 2 <= len(r[i].strip()) <= 4:
                                    names.add(r[i].strip())
            elif p.suffix in (".md", ".txt"):
                for line in read_text_any(p).splitlines():
                    if line.startswith("参会"):
                        names |= {x.strip() for x in re.split(r"[、，,：:]", line)[1:] if 2 <= len(x.strip()) <= 4}
        except Exception:
            pass
    names -= {"全勤", "合计", "总计", "备注", "姓名"}
    # 名字的"去姓"叫法（晓雨、一鸣）
    names |= {n[1:] for n in list(names) if len(n) == 3}
    return sorted(names, key=len, reverse=True)

class Deid:
    def __init__(self, meta):
        self.names = collect_names(meta); self.map = {}
    def name_token(self, n):
        if n not in self.map:
            self.map[n] = f"⟨人名{sum(1 for v in self.map.values() if v.startswith('⟨人名')) + 1}⟩"
        return self.map[n]
    def scrub(self, text):
        for n in self.names:
            if n in text: text = text.replace(n, self.name_token(n))
        text = re.sub(r"[\w.]+@[\w.]+", "⟨邮箱⟩", text)
        text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "⟨手机号⟩", text)
        text = re.sub(r"\d{6,}[\dXx]*", "⟨编号⟩", text)
        return text
    def audit(self, text, forbidden_extra=()):
        bad = [n for n in self.names if n in text] + [f for f in forbidden_extra if f and f in text]
        if re.search(r"\d{6,}", text): bad.append("长数字串")
        if bad: raise ValueError(f"出站审计拒绝发送，包含：{bad[:5]}")
        return text
