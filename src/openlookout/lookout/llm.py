"""云端模型调用（OpenAI 兼容接口）。Key 只从 ~/.config/ai-butler/mimo.env 读，不打印、不落盘。
每次调用把"发出去的完整内容"写进 runs/<run>/outbound/，方便人工审查（隐私预览）；把用量写进 llm_log.jsonl。"""
import json, os, re, time
from pathlib import Path
import requests

def _env():
    env = {}
    for line in open(os.path.expanduser("~/.config/ai-butler/mimo.env"), encoding="utf-8-sig"):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1); env[k] = v.strip().strip('"').strip("'")
    return env

class LLM:
    def __init__(self, run_dir, model="mimo-v2.6-flash"):
        e = _env(); self._key = e["MIMO_API_KEY"]; self.base = e["MIMO_BASE_URL"].rstrip("/")
        self.model = model; self.run_dir = Path(run_dir); (self.run_dir / "outbound").mkdir(parents=True, exist_ok=True)
        self.n = 0

    def chat(self, step, system, user, max_tokens=4000, model=None, temperature=0.2):
        model = model or self.model; self.n += 1
        tag = f"{self.n:02d}_{step}_{model}"
        (self.run_dir / "outbound" / f"{tag}.txt").write_text(f"[system]\n{system}\n\n[user]\n{user}", encoding="utf-8")
        t = time.time(); err = None
        for attempt in range(3):
            try:
                r = requests.post(self.base + "/chat/completions", headers={"Authorization": "Bearer " + self._key},
                                  json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                        "max_tokens": max_tokens, "temperature": temperature}, timeout=300)
                r.raise_for_status(); j = r.json(); break
            except Exception as ex:
                err = str(ex)[:200]; time.sleep(3)
        else:
            raise RuntimeError(f"LLM call failed: {err}")
        dt = time.time() - t
        msg = j["choices"][0]["message"]; content = msg.get("content") or ""
        u = j.get("usage", {})
        rec = {"step": step, "model": model, "latency_s": round(dt, 2), "prompt_tokens": u.get("prompt_tokens"),
               "completion_tokens": u.get("completion_tokens"),
               "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"), "chars_sent": len(system) + len(user)}
        with open(self.run_dir / "llm_log.jsonl", "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        (self.run_dir / "outbound" / f"{tag}.response.txt").write_text(content, encoding="utf-8")
        return content, rec

def _balance(s):
    """迭代 3：模型输出长 JSON 时偶尔少一个右括号。按括号栈补齐（只补结构，不改内容）。"""
    out, st, ins, esc = [], [], False, False
    pair = {"{": "}", "[": "]"}
    for ch in s:
        if ins:
            out.append(ch)
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': ins = False
            continue
        if ch == '"': ins = True
        elif ch in pair: st.append(pair[ch])
        elif ch in "}]":
            while st and st[-1] != ch: out.append(st.pop())
            if st: st.pop()
            else: continue
        out.append(ch)
    return "".join(out) + "".join(reversed(st))

def parse_json(text):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    s = m.group(1) if m else text
    i = min([x for x in (s.find("{"), s.find("[")) if x >= 0] or [0])
    s = s[i:]
    try: return json.loads(s)
    except json.JSONDecodeError:
        try: return json.loads(_balance(s.strip().rstrip("`").strip()))
        except json.JSONDecodeError: pass
        # 截掉尾部多余文字
        for end in range(len(s), 0, -1):
            if s[end - 1] in "}]":
                try: return json.loads(s[:end])
                except json.JSONDecodeError: continue
        raise
