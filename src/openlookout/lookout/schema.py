"""把本机文件变成"可以发出去的结构描述"：只有列名、类型、少量非敏感类别值，没有任何数据行。"""
from pathlib import Path
import openpyxl
from .common import read_table, to_num, to_date
from .deid import NAME_COL

def schema_of(path, deid):
    h, rows = read_table(path)
    cols = []
    for i, c in enumerate(h):
        vals = [r[i] for r in rows if i < len(r) and r[i] not in (None, "")]
        if NAME_COL.search(c): t = "人名"
        elif vals and all(to_date(v) for v in vals[:10]): t = "日期(YYYY-MM-DD)"
        elif vals and sum(to_num(v) is not None for v in vals) > 0.9 * len(vals): t = "数字"
        else:
            d = sorted({str(v) for v in vals})
            if 1 < len(d) <= 6 and all(len(x) <= 8 for x in d): t = "类别，取值: " + " / ".join(deid.scrub(x) for x in d)
            else:
                d2 = {str(v) for v in vals}
                kw = sorted({x for x in d2 if len(x) <= 8})
                t = "文本" + (f"（常见短值: {' / '.join(deid.scrub(x) for x in kw[:6])}，其余为空）" if len(d2) <= 8 and kw else "")
        cols.append(f"{c}: {t}")
    return f"列 = [{'; '.join(cols)}]；约 {len(rows)} 行"

def report_layout(path, deid):
    ws = openpyxl.load_workbook(path, data_only=True).active
    lines, table = [], None
    for row in ws.iter_rows(min_row=1, values_only=True):
        cells = [c for c in row if c not in (None, "")]
        if not cells: continue
        if table is not None:
            table["n"] += 1; continue
        if len(cells) >= 3 and all(isinstance(c, str) for c in cells):
            table = {"cols": cells, "n": 0}; continue
        if len(cells) == 1: lines.append(f"标题行: {deid.scrub(str(cells[0]))}")
        else:
            v = cells[1]
            if isinstance(v, float):
                dec = len(repr(v).split(".")[1]) if "." in repr(v) else 0
                t = f"小数（保留 {dec} 位）"   # 迭代 2：告诉模型精度，否则它会自己挑 round(2)
            else:
                t = "整数" if isinstance(v, int) else ("日期区间，格式 '<周一 YYYY-MM-DD> ~ <周五 YYYY-MM-DD>'" if to_date(v) else "文本")
            lines.append(f"A列标签 '{cells[0]}' → B列: {t}")
    if table: lines.append(f"下方一张表，表头 = {table['cols']}，{table['n']} 行（每行一个人）")
    return "\n".join(lines)
