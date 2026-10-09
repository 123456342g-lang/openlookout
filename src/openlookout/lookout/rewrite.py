"""只重跑"写卡片"这一步（检测、拼装、验证结果都沿用已有的 result.json），用来便宜地迭代文案、比较模型。
用法：python3 -m lookout.rewrite runs/final_flash --writer-model mimo-v2.6-pro --tag w2"""
import argparse, json, shutil
from pathlib import Path
from .common import load_meta
from .deid import Deid
from .llm import LLM, parse_json
from .run import WRITER_SYS, slot_type
from . import inbox

ap = argparse.ArgumentParser(); ap.add_argument("run"); ap.add_argument("--writer-model", default="mimo-v2.6-flash"); ap.add_argument("--tag", default="rw")
a = ap.parse_args()
src = Path(a.run); s = json.loads((src / "result.json").read_text(encoding="utf-8"))
dst = src.parent / f"{src.name}__{a.tag}"
if dst.exists(): shutil.rmtree(dst)
shutil.copytree(src, dst, ignore=shutil.ignore_patterns("outbound", "llm_log.jsonl", "prepared", "inbox.*"))
deid = Deid(load_meta()); llm = LLM(dst, a.writer_model)
fmap = {f["id"]: f for f in s["findings"]}
blocks = []
for i, r in s["results"].items():
    if r["status"] in ("failed", "skipped"): continue
    f = fmap[i]; j = s["judge"].get(i, {})
    blocks.append(f"### id={i} 类型={f['kind']} 紧急度={j.get('urgency')}\n发现：{f['desc']}\n为什么重要：{j.get('why','')}\n"
                  f"准备状态：{r['status']}；验证摘要：{json.dumps(r.get('verify_deid', {}), ensure_ascii=False)}\n"
                  f"已准备的文件数：{len(r.get('artifacts', []))}；工作流说明：{(r.get('workflow') or {}).get('explain', '无')}\n"
                  f"可用占位符：{', '.join('{'+k+'}(' + slot_type(v) + ')' for k, v in r.get('slots', {}).items())}")
body = deid.scrub("\n\n".join(blocks)); deid.audit(body)
txt, rec = llm.chat("write_cards", WRITER_SYS, "给下面每一条写一张卡片：\n\n" + body, max_tokens=6000)
s["cards"] = {c["id"]: c for c in parse_json(txt)}
s["llm"] = [x for x in s["llm"] if x["step"] != "write_cards"] + [rec]
s["writer_model"] = a.writer_model
(dst / "result.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
inbox.render(s, dst)
print("rewrote", dst, rec)
