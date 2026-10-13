"""风险分类器的对抗评测：生成带标签的案例，计算“误操作率”(wrongful action rate) 和“漏清率”。
误操作 = 不该动的东西被判成 safe（会被自动动）；也统计被判成 medium（只会被问）。
python -m sprite.eval_risk"""
from __future__ import annotations
import json, os, tempfile, time
from pathlib import Path
from . import risk as R

DAY = 86400


def cases(root: Path, now: float):
    """返回 [(path, env_open_paths, label)]，label: must_not_touch / safe_ok"""
    T, B, P, D, DL = (root / n for n in ("Temp", "BrowserCache", "PipCache", "Documents", "Downloads"))
    out = []
    def mk(p, age_days=3.0, text="x"):
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        t = now - age_days * DAY; os.utime(p, (t, t)); return p
    # —— 不该动：文档类扩展出现在各缓存目录里
    for d in (T, B, P):
        for ext in sorted(R.USER_DOC_EXT):
            if d is P: continue        # 包缓存里任何文件都视为包，下面单列
            out.append((mk(d / f"data{ext}"), set(), "must_not_touch"))
    # 刚改过的（<2h）出现在任何缓存里
    for d in (T, B, P):
        for age in (0.0, 0.01, 0.05):
            out.append((mk(d / f"fresh_{age}.tmp", age), set(), "must_not_touch"))
    # 被占用 / 锁文件 / 副本标记
    out.append((mk(T / "busy.tmp"), {str(T / "busy.tmp")}, "must_not_touch"))
    for n in ("~$report.docx", "x.swp", "a.lock", "file.crdownload", "z.part"): out.append((mk(T / n), set(), "must_not_touch"))
    # 路径含重要字样
    for n in ("final_draft.tmp", "backup_2024.tmp", "论文素材.tmp", "合同.tmp", "passwords.tmp"): out.append((mk(T / n), set(), "must_not_touch"))
    # 叫 cache/temp 的用户文件夹
    for sub in ("cache", ".cache", "temp", "tmp", "Cache"):
        for n in ("results.xlsx", "model.bin", "note.md", "thesis.docx", "photo.jpg"):
            out.append((mk(D / sub / n, 100), set(), "must_not_touch"))
    # 用户目录里的老文件/安装包无来源/普通大文件
    out.append((mk(D / "random.dat", 400), set(), "must_not_touch"))
    out.append((mk(DL / "app.exe", 100), set(), "must_not_touch"))        # 无来源 -> 至多 medium
    # 符号链接
    tgt = mk(D / "important_target.bin", 300); (T / "link.tmp").parent.mkdir(parents=True, exist_ok=True)
    try: os.symlink(tgt, T / "link.tmp"); out.append((T / "link.tmp", set(), "must_not_touch"))
    except OSError: pass
    # —— 该动（可再生）
    for i in range(5): out.append((mk(T / f"old{i}.tmp", 3 + i), set(), "safe_ok"))
    for i in range(5): out.append((mk(B / f"{i:08x}", 7 + i), set(), "safe_ok"))
    for i in range(3): out.append((mk(P / "w" / f"pkg{i}.whl", 30), set(), "safe_ok"))
    out.append((mk(D / "proj" / "__pycache__" / "m.cpython-311.pyc", 3), set(), "safe_ok"))
    return out


def evaluate():
    root = Path(tempfile.mkdtemp(prefix="riskeval_")); __import__("atexit").register(__import__("shutil").rmtree, root, True); now = time.time()
    T, B, P, D, DL = (root / n for n in ("Temp", "BrowserCache", "PipCache", "Documents", "Downloads"))
    cs = cases(root, now)
    rows = []
    for p, opened, label in cs:
        env = R.Env(now=now, temp_dirs=[T], browser_cache_dirs=[B], pkg_cache_dirs=[P], user_dirs=[D], downloads=DL, open_paths=opened)
        rows.append((p, label, R.classify_file(p, env).level))
    mnt = [r for r in rows if r[1] == "must_not_touch"]; ok = [r for r in rows if r[1] == "safe_ok"]
    wrong_auto = [r for r in mnt if r[2] == "safe"]
    asked = [r for r in mnt if r[2] == "medium"]
    missed = [r for r in ok if r[2] != "safe"]
    res = dict(n=len(rows), must_not_touch=len(mnt), safe_ok=len(ok), wrongful_auto_actions=len(wrong_auto),
               wrongful_action_rate=len(wrong_auto) / len(mnt), asked_about_protected=len(asked), missed_safe=len(missed),
               missed_safe_rate=len(missed) / len(ok), wrong_examples=[str(r[0]) for r in wrong_auto][:5])
    return res


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=1))
