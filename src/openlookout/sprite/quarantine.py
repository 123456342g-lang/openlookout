"""可还原的隔离区：不删除，只把东西移进隔离区并记下还原映射（原路径、哈希、大小、原因）。
同一磁盘上直接移动不会腾出空间，所以同盘时用 zip 压缩后再移走原文件（校验通过才移除原文件），真实腾出的空间如实报告。"""
from __future__ import annotations
import hashlib, json, os, shutil, time, uuid, zipfile
from pathlib import Path


def sha(p: Path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(chunk): h.update(b)
    return h.hexdigest()


class Quarantine:
    def __init__(self, home: Path):
        self.dir = Path(home) / "quarantine"; self.dir.mkdir(parents=True, exist_ok=True)
        self.map = self.dir / "restore_map.jsonl"

    def _entries(self):
        if not self.map.exists(): return []
        return [json.loads(l) for l in self.map.read_text("utf-8").splitlines() if l.strip()]

    def _write(self, es): self.map.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in es), "utf-8")

    def put(self, path: Path, reason: str, mode: str = "auto", regen: bool = False, copy: str | None = None, now: float | None = None) -> dict:
        path = Path(path)
        if path.is_symlink() or not path.is_file(): raise ValueError("只隔离普通文件")
        qid = uuid.uuid4().hex[:10]; size = path.stat().st_size; h = sha(path)
        same_vol = os.stat(path).st_dev == os.stat(self.dir).st_dev
        mode = ("zip" if same_vol and size < (2 << 30) else "move") if mode == "auto" else mode
        if mode == "zip":
            z = self.dir / f"{qid}.zip"
            with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf: zf.write(path, "data")
            with zipfile.ZipFile(z) as zf:
                if zf.testzip() is not None: z.unlink(); raise IOError("压缩校验失败，原文件未动")
            stored = z.stat().st_size
            path.unlink()                              # 已校验的压缩副本在隔离区，这是“移入隔离区”的一半
            loc = z.name
        else:
            dst = self.dir / f"{qid}_{path.name}"
            shutil.copy2(path, dst)
            if sha(dst) != h: dst.unlink(); raise IOError("复制校验失败，原文件未动")
            path.unlink(); loc = dst.name; stored = size
        e = dict(id=qid, orig=str(path), size=size, stored=stored, mode=mode, loc=loc, sha=h, reason=reason, status="held", regen=regen, copy=copy, ts=now or time.time())
        with self.map.open("a", encoding="utf-8") as f: f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e

    def restore(self, qid: str) -> Path:
        es = self._entries()
        for e in es:
            if e["id"] == qid and e["status"] == "held":
                dst = Path(e["orig"]); src = self.dir / e["loc"]
                if dst.exists(): dst = dst.with_name(dst.stem + ".restored" + dst.suffix)      # 从不覆盖
                dst.parent.mkdir(parents=True, exist_ok=True)
                if e["mode"] == "zipdir":
                    with zipfile.ZipFile(src) as zf:
                        for n in zf.namelist():
                            t = dst / n[len("data/"):]; t.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(n) as i, open(t, "wb") as o: shutil.copyfileobj(i, o)
                    src.unlink(); e["status"] = "restored"; self._write(es); return dst
                if e["mode"] == "zip":
                    with zipfile.ZipFile(src) as zf, zf.open("data") as i, open(dst, "wb") as o: shutil.copyfileobj(i, o)
                    src.unlink()
                else: shutil.move(str(src), str(dst))
                if sha(dst) != e["sha"]: raise IOError("还原后哈希不一致")
                e["status"] = "restored"; self._write(es); return dst
        raise KeyError(qid)

    def held(self): return [e for e in self._entries() if e["status"] == "held"]

    # ---- 目录（构建产物等）：整个目录 zip，校验后才移除原目录
    def put_dir(self, d: Path, reason: str, regen: bool = True, now: float | None = None) -> dict:
        d = Path(d)
        if d.is_symlink() or not d.is_dir(): raise ValueError("只隔离普通目录")
        qid = uuid.uuid4().hex[:10]; z = self.dir / f"{qid}.zip"; files = [p for p in d.rglob("*") if p.is_file()]
        if any(p.is_symlink() for p in d.rglob("*")): raise ValueError("目录里有符号链接")
        hs = {str(p.relative_to(d)): sha(p) for p in files}
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files: zf.write(p, "data/" + str(p.relative_to(d)))
        with zipfile.ZipFile(z) as zf:
            if zf.testzip() is not None or len([n for n in zf.namelist()]) != len(files): z.unlink(); raise IOError("压缩校验失败，原目录未动")
        size = sum(p.stat().st_size for p in files); shutil.rmtree(d)
        e = dict(id=qid, orig=str(d), size=size, stored=z.stat().st_size, mode="zipdir", loc=z.name, sha=json.dumps(hs, sort_keys=True), reason=reason,
                 status="held", regen=regen, copy=None, ts=now or time.time())
        with self.map.open("a", encoding="utf-8") as f: f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e

    # ---- 到期处理（由状态驱动调用，不是定时器）：只有 “过了 N 天 且 (可再生 或 副本仍然逐字节一致)” 才可自动永久清除；其余只列出来问
    def classify_expiry(self, now: float, days: float = 14, copy_ok=None):
        auto, ask = [], []
        for e in self.held():
            if now - e.get("ts", now) < days * 86400: continue
            if e.get("regen"): auto.append((e, "可再生")); continue
            c = e.get("copy")
            if c and Path(c).is_file() and e["mode"] != "zipdir" and sha(Path(c)) == e["sha"] and (copy_ok is None or copy_ok(Path(c))): auto.append((e, "副本仍一致")); continue
            ask.append(e)
        return auto, ask

    def purge(self, qid: str, why: str):
        es = self._entries()
        for e in es:
            if e["id"] == qid and e["status"] == "held":
                (self.dir / e["loc"]).unlink(missing_ok=True); e["status"] = "expired"; self._write(es)
                with (self.dir / "expired.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(dict(id=qid, orig=e["orig"], size=e["size"], why=why, ts=time.time()), ensure_ascii=False) + "\n")
                return True
        return False
