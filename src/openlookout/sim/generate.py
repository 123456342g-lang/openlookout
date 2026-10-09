"""模拟一个真实用户四周的电脑使用，输出：
  sim_home/          她磁盘上的真实文件（表格、笔记、发票、账单、手工周报）
  capture/events.jsonl  确定性记录层会采到的事件（窗口/网址/文件/剪贴板/表单）
  ground_truth/      埋进数据里的问题清单（检测器永远不读这个目录）
人物：林晓雨，某大学化学学院研二，金纳米颗粒课题组，兼课题组助管。
模拟时间：2026-08-31(周一) ~ 2026-09-25(周五) 08:50（"现在"）。
"""
import csv, hashlib, json, random, shutil
from datetime import date, datetime, timedelta
from pathlib import Path
import openpyxl

random.seed(20260925)
ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "sim_home" / "xiaoyu"
CAP = ROOT / "capture"
NOW = datetime(2026, 9, 25, 8, 50)
START = date(2026, 8, 31)

DOCS = HOME / "文档" / "课题组"
NOTES = HOME / "文档" / "笔记"
REPORTS = HOME / "文档" / "周报"
DL = HOME / "下载"
INV = DL / "发票"
for d in (DOCS, NOTES, REPORTS, DL, INV):
    d.mkdir(parents=True, exist_ok=True)

EXP = DOCS / "实验记录_2026秋.xlsx"
SUP = DOCS / "耗材领用.csv"
PROG = DOCS / "组会进度表.xlsx"

events = []
def ev(ts, type_, **kw):
    e = {"ts": ts.strftime("%Y-%m-%dT%H:%M:%S+08:00"), "type": type_}
    e.update({k: v for k, v in kw.items() if v is not None})
    events.append(e)

def h(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]

CALC = "libreoffice-calc"; CHROME = "google-chrome"; PDF = "evince"; WX = "wechat"; CALCAPP = "gnome-calculator"; TERM = "gnome-terminal"; CODE = "code"

class Cursor:
    def __init__(self, t): self.t = t
    def focus(self, app, title, dur, url=None):
        ev(self.t, "focus", app=app, title=title, url=url, dur_s=int(dur))
        self.t += timedelta(seconds=int(dur))
    def open(self, path, app):
        ev(self.t, "file_open", path=str(path.relative_to(HOME.parent)), app=app)
    def save(self, path, app):
        ev(self.t, "file_save", path=str(path.relative_to(HOME.parent)), app=app)
    def copy(self, text, src_app, src_title, dst_app, dst_title):
        ev(self.t, "clipboard", src_app=src_app, src_title=src_title, dst_app=dst_app, dst_title=dst_title,
           len=len(text), hash=h(text), text=text)  # text 只在本机加密短期缓冲中，不出本机
        self.t += timedelta(seconds=random.randint(4, 15))
    def form(self, url, label, via):
        ev(self.t, "form_edit", app=CHROME, url=url, field_label=label, via=via)
    def wait(self, s): self.t += timedelta(seconds=int(s))

def T(d, hh, mm): return datetime(d.year, d.month, d.day, hh, mm, random.randint(0, 59))
def title_of(p): return f"{p.name} - LibreOffice Calc"

# ---------------- 实验数据 ----------------
REAG = {"氯金酸": 339.79, "柠檬酸钠": 258.07, "硼氢化钠": 37.83, "硝酸银": 169.87, "抗坏血酸": 176.12}
SEARCH_VARIANTS = {
    "氯金酸": ["氯金酸 摩尔质量", "氯金酸摩尔质量", "HAuCl4 摩尔质量"],
    "硼氢化钠": ["硼氢化钠 摩尔质量", "硼氢化钠摩尔质量", "NaBH4 分子量"],
    "硝酸银": ["硝酸银 摩尔质量", "硝酸银的摩尔质量"],
    "抗坏血酸": ["抗坏血酸 摩尔质量"],
    "柠檬酸钠": ["柠檬酸钠 摩尔质量"],
}
workdays = [START + timedelta(days=i) for i in range(26) if (START + timedelta(days=i)).weekday() < 5]
workdays = [d for d in workdays if datetime(d.year, d.month, d.day) < NOW.replace(hour=0)]  # 到 9/24 为止
exp_days = [d for d in workdays if d.weekday() <= 3 and d not in (date(2026, 9, 9),)]  # 周一到周四做实验
exp_rows = []
drift_start = date(2026, 9, 14)
xrd_left = 12
for d in exp_days:
    k = workdays.index(d)
    drift = 0.0 if d < drift_start else 0.0052 * (sum(1 for x in exp_days if drift_start <= x <= d))
    ctrl = round(0.500 + drift + random.gauss(0, 0.0035), 3)
    exp_rows.append([d, f"CTRL-{d:%m%d}", "对照", "柠檬酸钠", 25.0, REAG["柠檬酸钠"], round(25.0 / REAG["柠檬酸钠"], 4), ctrl, "", "林晓雨"])
    for i in range(random.randint(3, 5)):
        r = random.choice(["氯金酸", "硼氢化钠", "硝酸银", "抗坏血酸"])
        m = round(random.uniform(5, 40), 1)
        a = round(random.uniform(0.35, 0.95) + drift, 3)
        note = ""
        if d <= date(2026, 9, 15) and xrd_left > 0 and random.random() < 0.55:
            note = "待测XRD"; xrd_left -= 1
        elif random.random() < 0.12:
            note = random.choice(["颜色偏紫", "重复一次", "离心不完全"])
        who = "林晓雨" if random.random() < 0.8 else "陈一鸣"
        exp_rows.append([d, f"S-{d:%m%d}-{i+1}", "样品", r, m, REAG[r], round(m / REAG[r], 4), a, note, who])

def write_exp(rows, upto):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "记录"
    ws.append(["日期", "样品编号", "类型", "试剂", "称量质量(mg)", "摩尔质量(g/mol)", "物质的量(mmol)", "吸光度A520", "备注", "操作人"])
    for r in rows:
        if r[0] <= upto: ws.append([r[0].isoformat()] + r[1:])
    wb.save(EXP)

# ---------------- 耗材 ----------------
ITEMS = [("移液枪头 200μL", "盒", 100), ("一次性离心管 1.5mL", "包", 35), ("丁腈手套 M", "盒", 48), ("超纯水桶", "桶", 60),
         ("比色皿 石英", "个", 120), ("称量纸", "包", 12), ("注射器滤头 0.22μm", "盒", 156), ("锡箔纸", "卷", 18)]
MEMBERS = ["林晓雨", "张浩", "李婷", "陈一鸣", "刘洋"]
sup_rows = []
for d in workdays:
    for _ in range(random.choice([0, 1, 1, 2])):
        it = random.choice(ITEMS); q = random.randint(1, 4)
        sup_rows.append([d, it[0], it[1], q, it[2], q * it[2], random.choice(MEMBERS)])
# 9/16 两盒枪头（这行就是 0918 周报里漏抄的那一行）
sup_rows.append([date(2026, 9, 16), "移液枪头 200μL", "盒", 2, 100, 200, "李婷"])
sup_rows.sort(key=lambda r: r[0])

def write_sup(upto):
    with open(SUP, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["领用日期", "品名", "单位", "数量", "单价", "金额", "领用人"])
        for r in sup_rows:
            if r[0] <= upto: w.writerow([r[0].isoformat()] + r[1:])

# ---------------- 组会进度表 ----------------
PROG_TEXT = {
    "张浩": [("完成金核银壳样品 TEM 表征", "整理 TEM 数据，写方法部分"), ("TEM 数据整理完，初稿方法部分写了一半", "补拍高分辨 TEM"),
            ("补拍高分辨 TEM，晶格条纹清楚", "开始写结果讨论"), ("结果讨论写了 2 页", "和王老师讨论图 3")],
    "李婷": [("调试紫外分光光度计新方法", "做标准曲线"), ("标准曲线 R²=0.998", "测 6 个浓度梯度"),
            ("6 个浓度梯度测完", "重复实验"), ("重复实验做了一半，有两个点偏高", "查原因")],
    "陈一鸣": [("学习合成流程，跟做 3 次", "独立合成一批"), ("独立合成一批，粒径偏大", "调整硼氢化钠用量"),
             ("调整还原剂用量后粒径 15nm 左右", "做 DLS"), ("DLS 测完，分布较窄", "整理数据")],
    "刘洋": [("文献调研 20 篇", "写综述提纲"), ("综述提纲完成", "写第一节"), ("第一节写完", "第二节"), ("综述第二节进行中", "投组内讨论")],
    "林晓雨": [("合成 4 批 AuNP，测吸光度", "做银包金"), ("银包金两批，吸光度稳定", "继续优化"),
             ("优化反应时间，整理 XRD 待测样", "继续合成"), ("合成 3 批，周报和报销", "继续合成")],
}
weeks = [date(2026, 8, 31) + timedelta(weeks=i) for i in range(4)]  # 周一
def prog_rows_upto(upto):
    rows = []
    for wi, wk in enumerate(weeks):
        upd = wk + timedelta(days=3)  # 周四汇总群消息
        if upd <= upto:
            for m in MEMBERS:
                a, b = PROG_TEXT[m][wi]; rows.append([upd, m, a, b])
    return rows
def write_prog(upto):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "进度"
    ws.append(["更新日期", "成员", "本周进展", "下周计划"])
    for r in prog_rows_upto(upto): ws.append([r[0].isoformat()] + r[1:])
    wb.save(PROG)

# ---------------- 手工周报 ----------------
def week_stats(mon):
    fri = mon + timedelta(days=4)
    ex = [r for r in exp_rows if mon <= r[0] <= fri]
    ctrl = [r[7] for r in ex if r[2] == "对照"]
    sp = [r for r in sup_rows if mon <= r[0] <= fri]
    return {"实验天数": len({r[0] for r in ex}), "样品数（不含对照）": sum(1 for r in ex if r[2] == "样品"),
            "对照平均吸光度": round(sum(ctrl) / len(ctrl), 3) if ctrl else 0,
            "耗材支出合计（元）": sum(r[5] for r in sp), "耗材领用次数": len(sp)}
def write_report(mon, path, tamper=None):
    fri = mon + timedelta(days=4); st = week_stats(mon)
    if tamper: st.update(tamper)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "周报"
    ws["A1"] = "金纳米课题组周报"; ws["A2"] = "统计周期"; ws["B2"] = f"{mon.isoformat()} ~ {fri.isoformat()}"
    for i, k in enumerate(["实验天数", "样品数（不含对照）", "对照平均吸光度", "耗材支出合计（元）", "耗材领用次数"]):
        ws.cell(4 + i, 1, k); ws.cell(4 + i, 2, st[k])
    ws["A10"] = "成员"; ws["B10"] = "本周进展"; ws["C10"] = "下周计划"
    rr = [r for r in prog_rows_upto(fri) if mon <= r[0] <= fri]
    for j, r in enumerate(rr): ws.cell(11 + j, 1, r[1]); ws.cell(11 + j, 2, r[2]); ws.cell(11 + j, 3, r[3])
    wb.save(path)

# ---------------- 发票 ----------------
SELLERS = ["北京博瑞生物科技有限公司", "上海泰坦科技股份有限公司", "国药集团化学试剂有限公司", "西安晶博仪器有限公司"]
invoices = []
inv_dates = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 2), date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 9),
             date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 21), date(2026, 9, 23)]
for i, d in enumerate(inv_dates):
    total = random.choice([200.00, 356.00, 1280.00, 89.50, 468.00, 2150.00, 175.00, 640.00, 96.00, 1530.00])
    tax = round(total - total / 1.13, 2); amt = round(total - tax, 2)
    no = "2611" + "".join(random.choice("0123456789") for _ in range(16))
    seller = SELLERS[i % 4]
    p = INV / f"dzfp_{no}.pdf.txt"
    p.write_text(f"""电子发票（普通发票）
发票号码：{no}
开票日期：{d.year}年{d.month:02d}月{d.day:02d}日
购买方信息 名称：西京大学 统一社会信用代码/纳税人识别号：12610000435230123X
销售方信息 名称：{seller} 统一社会信用代码/纳税人识别号：91{random.randint(10**15, 10**16-1)}
项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额
*实验室耗材*{random.choice(ITEMS)[0]} 批 1 {amt:.2f} {amt:.2f} 13% {tax:.2f}
合 计 ¥{amt:.2f} ¥{tax:.2f}
价税合计（大写） （略） （小写）¥{total:.2f}
开票人：{random.choice(['王敏', '赵丽', '孙强'])}
""", encoding="utf-8")
    invoices.append({"path": p, "no": no, "date": f"{d.year}年{d.month:02d}月{d.day:02d}日", "seller": seller,
                     "total": f"{total:.2f}", "tax": f"{tax:.2f}", "dl": d})

# ---------------- 账单 ----------------
def bill(month, rows):
    p = DL / f"支付宝交易明细_2026{month:02d}.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        f.write("支付宝交易明细\n账号：xiaoyu****@163.com\n起始日期：[2026-%02d-01 00:00:00] 终止日期：[2026-%02d-30 23:59:59]\n" % (month, month))
        f.write("---------------------------------交易明细列表------------------------------------\n")
        w = csv.writer(f); w.writerow(["交易时间", "交易分类", "交易对方", "商品说明", "收/支", "金额", "支付方式", "交易状态", "交易订单号"])
        for r in sorted(rows): w.writerow(r)
    return p
def bill_rows(month, days):
    rows = []
    for dd in range(1, days + 1):
        d = date(2026, month, dd)
        if month == 9 and d >= NOW.date(): break
        rows.append([f"{d} 11:{random.randint(30,59):02d}:{random.randint(0,59):02d}", "餐饮美食", "西京大学第二食堂", "消费", "支出", f"{random.choice([12,13,14,15,16,18]):.2f}", "余额宝", "交易成功", f"2026{d:%m%d}2200{random.randint(10**9,10**10-1)}"])
        if random.random() < 0.7:
            rows.append([f"{d} 17:{random.randint(20,59):02d}:{random.randint(0,59):02d}", "餐饮美食", "美团外卖", "外卖订单", "支出", f"{random.choice([15,18,22,25]):.2f}", "余额宝", "交易成功", f"2026{d:%m%d}2200{random.randint(10**9,10**10-1)}"])
        if random.random() < 0.4:
            rows.append([f"{d} 09:{random.randint(0,30):02d}:{random.randint(0,59):02d}", "餐饮美食", "瑞幸咖啡", "生椰拿铁", "支出", "9.90", "余额宝", "交易成功", f"2026{d:%m%d}2200{random.randint(10**9,10**10-1)}"])
    return rows
aug = bill_rows(8, 31)
aug += [["2026-08-12 09:01:33", "文化休闲", "百度网盘", "超级会员连续包月", "支出", "30.00", "花呗", "交易成功", "2026081222001100000001"],
        ["2026-08-15 00:02:10", "文化休闲", "腾讯视频", "VIP会员自动续费", "支出", "25.00", "花呗", "交易成功", "2026081522001100000002"],
        ["2026-08-18 00:00:41", "文化休闲", "QQ音乐", "豪华绿钻自动续费", "支出", "15.00", "花呗", "交易成功", "2026081822001100000003"],
        ["2026-08-20 10:12:00", "通讯", "中国移动", "话费充值", "支出", "50.00", "余额宝", "交易成功", "2026082022001100000004"],
        ["2026-08-26 21:40:00", "日用百货", "淘宝", "宿舍收纳盒", "支出", "39.90", "花呗", "交易成功", "2026082622001100000005"]]
sep = bill_rows(9, 30)
sep += [["2026-09-12 09:01:12", "文化休闲", "百度网盘", "超级会员连续包月", "支出", "30.00", "花呗", "交易成功", "2026091222001100000011"],
        ["2026-09-12 09:01:47", "文化休闲", "百度网盘", "超级会员连续包月", "支出", "30.00", "花呗", "交易成功", "2026091222001100000012"],
        ["2026-09-15 00:01:52", "文化休闲", "腾讯视频", "VIP会员自动续费", "支出", "30.00", "花呗", "交易成功", "2026091522001100000013"],
        ["2026-09-18 00:00:37", "文化休闲", "QQ音乐", "豪华绿钻自动续费", "支出", "15.00", "花呗", "交易成功", "2026091822001100000014"],
        ["2026-09-19 14:22:10", "日用百货", "淘宝", "实验服", "支出", "68.00", "花呗", "交易成功", "2026091922001100000015"]]

# ---------------- 组会纪要（截止日藏在中间） ----------------
MEET = {
date(2026, 8, 31): """# 组会纪要 8.31

参会：王老师、张浩、李婷、陈一鸣、刘洋、林晓雨

## 1. 新学期安排
- 王老师：这学期重点是把金核银壳那篇投出去，张浩牵头。
- 9 月 9 日前大家完成研究生选课，别忘了。
- 实验室卫生值日表照旧，每周一换人。

## 2. 进展
- 张浩：TEM 约好了，周三拍。
- 李婷：紫外新方法还在调。
- 陈一鸣：刚进组，先跟晓雨学合成。

## 3. 其他
- 液氮这学期改成每周二送。
""",
date(2026, 9, 7): """# 组会纪要 9.7

参会：王老师、张浩、李婷、陈一鸣、刘洋、林晓雨

## 1. 张浩 TEM 结果
- 金核银壳形貌不错，壳层厚度大概 3nm。王老师建议补高分辨。
- 图 2 的标尺要统一。

## 2. 李婷 方法开发
- 标准曲线线性还行，下周做浓度梯度。
- 比色皿要用石英的，塑料的在 300nm 以下吸收太强。

## 3. 测试安排
- 王老师：测试中心这学期 XRD 排队很长。这批标了"待测XRD"的样品，晓雨统一整理一张送样表（样品编号、成分、制备日期），9月28日前交到分析测试中心，过了这批要排到 11 月。
- 拉曼还是找物理学院那台，提前一周约。

## 4. 其他
- 新来的陈一鸣安全培训周五前要完成。
- 下周组会改到周一下午三点。
""",
date(2026, 9, 14): """# 组会纪要 9.14

参会：王老师、张浩、李婷、陈一鸣、刘洋、林晓雨

## 1. 进展
- 张浩：高分辨 TEM 拍完，晶格条纹清楚。
- 陈一鸣：独立合成一批，粒径偏大，硼氢化钠可能加少了。
- 林晓雨：银包金做了两批。

## 2. 讨论
- 张浩：晓雨把 8 月份的吸光度原始数据发我一份，写方法要用。
- 刘洋综述提纲王老师看过了，第二节再压缩一下。

## 3. 其他
- 实验室冰箱下周除霜，东西先挪到 2 号冰箱。
""",
date(2026, 9, 21): """# 组会纪要 9.21

参会：王老师、张浩、李婷、陈一鸣、刘洋、林晓雨

## 1. 进展
- 李婷：重复实验有两个点偏高，怀疑温度。
- 陈一鸣：粒径调到 15nm 左右了，DLS 分布窄。

## 2. 安排
- 中期答辩定在 11 月 20 日，10 月 30 日前交中期报告初稿。
- 国庆期间实验室开放，需要来的在群里报备。
""",
}

# ================= 生成四周的事件 =================
mail = "https://mail.xjtu-like.edu.cn/coremail/"
WSBX = "https://cwc.xijing.edu.cn/wsbx/bill/new"
written_exp = []
for d in [START + timedelta(days=i) for i in range(26)]:
    dt0 = datetime(d.year, d.month, d.day)
    if dt0.date() > NOW.date(): break
    c = Cursor(T(d, 8, random.randint(40, 58)))
    if dt0.date() == NOW.date():
        c.focus(CHROME, "收件箱 - 西京大学邮箱", 300, mail); break
    weekend = d.weekday() >= 5
    if not weekend:
        c.focus(CHROME, "收件箱 - 西京大学邮箱", random.randint(120, 400), mail)
        if random.random() < 0.5:
            c.focus(CHROME, "通知公告 - 西京大学研究生院", random.randint(30, 90), "https://gs.xijing.edu.cn/tzgg.htm")
        q = random.choice(["金纳米颗粒 银壳 生长机理", "AuNP 表面等离子共振 520nm", "柠檬酸钠还原法 粒径控制", "core-shell Au@Ag optical", "种子生长法 金纳米棒"])
        c.focus(CHROME, f"{q} - 中国知网", random.randint(600, 1800), f"https://kns.cnki.net/kns8s/search?q={q}")
    # 实验日：每个试剂都要查一次摩尔质量
    if d in exp_days:
        c.t = T(d, 9, random.randint(30, 59)); c.wait(0)
        c.open(EXP, CALC); c.focus(CALC, title_of(EXP), random.randint(60, 200))
        todays = [r for r in exp_rows if r[0] == d]
        for reag in sorted({r[3] for r in todays if r[2] == "样品"}):
            if random.random() < 0.85:
                q = random.choice(SEARCH_VARIANTS[reag])
                c.focus(CHROME, f"{q}_百度搜索", random.randint(25, 70), f"https://www.baidu.com/s?wd={q.replace(' ', '+')}")
                c.copy(f"{REAG[reag]}", CHROME, f"{q}_百度搜索", CALC, title_of(EXP))
                c.focus(CALC, title_of(EXP), random.randint(40, 120))
        c.wait(random.randint(1800, 5400))
        c.focus(CALC, title_of(EXP), random.randint(300, 700)); write_exp(exp_rows, d); c.save(EXP, CALC)
    # 耗材：有领用就打开 csv 记一笔
    if any(r[0] == d for r in sup_rows):
        c.t = T(d, 13, random.randint(30, 59)); c.open(SUP, CALC)
        c.focus(CALC, "耗材领用.csv - LibreOffice Calc", random.randint(60, 180)); write_sup(d); c.save(SUP, CALC)
    # 周一组会记纪要
    if d in MEET:
        p = NOTES / f"组会纪要_{d:%m%d}.md"
        c.t = T(d, 15 if d >= date(2026, 9, 14) else 14, random.randint(0, 10))
        c.open(p, CODE); c.focus(CODE, f"{p.name} - Visual Studio Code", random.randint(3000, 4200))
        p.write_text(MEET[d], encoding="utf-8"); c.save(p, CODE)
    # 周四：报销（9/3, 9/10, 9/17），每张发票 5 个字段从 PDF 抄进网页
    if d in (date(2026, 9, 3), date(2026, 9, 10), date(2026, 9, 17)):
        c.t = T(d, 14, random.randint(0, 20))
        todo = [iv for iv in invoices if iv["dl"] <= d and not iv.get("done")]
        c.focus(CHROME, "网上报销系统 - 西京大学财务处", random.randint(60, 120), WSBX)
        for iv in todo:
            c.open(iv["path"], PDF)
            pt = f"{iv['path'].name} — 文档查看器"
            c.focus(PDF, pt, random.randint(15, 40))
            for label, val in [("发票号码", iv["no"]), ("开票日期", iv["date"]), ("销售方名称", iv["seller"]), ("价税合计", iv["total"]), ("税额", iv["tax"])]:
                c.copy(val, PDF, pt, CHROME, "填写报销单 - 网上报销系统")
                c.focus(CHROME, "填写报销单 - 网上报销系统", random.randint(8, 25), WSBX); c.form(WSBX, label, "paste")
                c.focus(PDF, pt, random.randint(5, 15))
            c.form(WSBX, "经费卡号", "typed"); c.form(WSBX, "报销事由", "typed")
            c.focus(CHROME, "填写报销单 - 网上报销系统", random.randint(40, 90), WSBX)
            iv["done"] = True
        c.focus(CHROME, "报销单已提交 - 网上报销系统", 20, WSBX.replace("new", "list"))
    # 发票下载
    for iv in invoices:
        if iv["dl"] == d:
            c2 = Cursor(T(d, 10, random.randint(30, 50))); c2.save(iv["path"], CHROME)
    # 周四下午：把群里的进度贴进进度表
    if d.weekday() == 3:
        c.t = T(d, 17, random.randint(0, 20)); write_prog(d)
        c.open(PROG, CALC)
        for m in MEMBERS:
            wi = weeks.index(d - timedelta(days=3))
            c.focus(WX, "金纳米课题组(6)", random.randint(15, 40))
            c.copy(PROG_TEXT[m][wi][0], WX, "金纳米课题组(6)", CALC, title_of(PROG))
            c.focus(CALC, title_of(PROG), random.randint(20, 60))
        c.save(PROG, CALC)
    # 周五下午：手工拼周报（9/4, 9/11, 9/18）
    if d.weekday() == 4:
        mon = d - timedelta(days=4)
        rp = REPORTS / f"周报_{d:%m%d}.xlsx"
        c.t = T(d, 15, random.randint(0, 15))
        prev = sorted(REPORTS.glob("周报_*.xlsx"))
        if prev: c.open(prev[-1], CALC); c.focus(CALC, title_of(prev[-1]), random.randint(30, 80))
        for p in (EXP, SUP, PROG): c.open(p, CALC)
        tamper = {"耗材支出合计（元）": week_stats(mon)["耗材支出合计（元）"] - 200} if d == date(2026, 9, 18) else None
        st = week_stats(mon)
        if tamper: st.update(tamper)
        seq = [(EXP, "样品数（不含对照）"), (EXP, "对照平均吸光度"), (SUP, "耗材支出合计（元）"), (SUP, "耗材领用次数")]
        for src, key in seq:
            for _ in range(random.randint(2, 4)):
                c.focus(CALC, title_of(src) if src != SUP else "耗材领用.csv - LibreOffice Calc", random.randint(40, 150))
                if src == SUP and random.random() < 0.6: c.focus(CALCAPP, "计算器", random.randint(20, 60))
                c.focus(CALC, title_of(rp), random.randint(20, 60))
            c.copy(str(st[key]), CALC, title_of(src), CALC, title_of(rp))
        for m in MEMBERS:
            wi = weeks.index(mon)
            c.focus(CALC, title_of(PROG), random.randint(10, 30))
            c.copy(PROG_TEXT[m][wi][0], CALC, title_of(PROG), CALC, title_of(rp))
            c.copy(PROG_TEXT[m][wi][1], CALC, title_of(PROG), CALC, title_of(rp))
            c.focus(CALC, title_of(rp), random.randint(10, 30))
        write_report(mon, rp, tamper); c.save(rp, CALC)
        c.focus(CHROME, "写信 - 西京大学邮箱", random.randint(60, 150), mail + "compose")
        c.open(rp, CHROME)
    # 9/8 去选课（纪要里的截止日，已经完成）
    if d == date(2026, 9, 8):
        c.t = T(d, 20, 10); c.focus(CHROME, "研究生选课系统 - 西京大学", 600, "https://yjsxk.xijing.edu.cn/xsxk")
        p = DL / "选课结果_2026秋.pdf.txt"; p.write_text("2026秋 研究生选课结果\n已选：高等无机化学、纳米材料表征、学术英语\n", encoding="utf-8"); c.save(p, CHROME)
    # 9/16 把 8 月吸光度数据发给张浩（纪要里的承诺，已经完成）
    if d == date(2026, 9, 16):
        c.t = T(d, 16, 30); c.focus(CHROME, "写信：8月吸光度原始数据 - 西京大学邮箱", 240, mail + "compose"); c.open(EXP, CHROME)
    # 9/22 下载账单，看了一眼
    if d == date(2026, 9, 22):
        c.t = T(d, 22, 5)
        pa = bill(8, aug); pb = bill(9, sep)
        for p in (pa, pb):
            c.save(p, CHROME); c.open(p, CALC); c.focus(CALC, f"{p.name} - LibreOffice Calc", random.randint(25, 50))
    # 晚上：娱乐（干扰项）
    c.t = T(d, 21 if not weekend else 15, random.randint(0, 50))
    for _ in range(random.randint(1, 4)):
        site = random.choice([("哔哩哔哩 (゜-゜)つロ 干杯~-bilibili", "https://www.bilibili.com/"), ("知乎 - 有问题，就会有答案", "https://www.zhihu.com/"),
                              ("淘宝网 - 淘！我喜欢", "https://www.taobao.com/")])
        c.focus(CHROME, site[0], random.randint(300, 2400), site[1])
    if random.random() < 0.15:
        c.focus(CHROME, "latex 表格 合并单元格_百度搜索", 60, "https://www.baidu.com/s?wd=latex+表格+合并单元格")

write_exp(exp_rows, date(2026, 9, 24)); write_sup(date(2026, 9, 24)); write_prog(date(2026, 9, 24))
events.sort(key=lambda e: e["ts"])
CAP.mkdir(exist_ok=True)
with open(CAP / "events.jsonl", "w", encoding="utf-8") as f:
    for e in events: f.write(json.dumps(e, ensure_ascii=False) + "\n")
meta = {"now": NOW.isoformat(), "user_home": str(HOME.relative_to(ROOT)), "watched_dirs": ["文档", "下载"]}
(CAP / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
# 这周（9/21~9/25）的周报还没做 —— 那就是"今天的活"
print(f"events={len(events)} exp_rows={len(exp_rows)} sup_rows={len(sup_rows)} invoices={len(invoices)}")
print("0918 真实耗材合计", week_stats(date(2026, 9, 14))["耗材支出合计（元）"])
print("ctrl", [(r[0].isoformat(), r[7]) for r in exp_rows if r[2] == "对照"])
