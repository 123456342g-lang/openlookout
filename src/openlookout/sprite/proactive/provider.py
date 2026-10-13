"""供应商配置：小精灵调用模型用的接口地址、协议、模型名和 key。
- 地址/协议/模型：sprite/proactive/provider.json（不含 key，可以进 git；环境变量 SPRITE_PROVIDER 可指向别的文件）。
- key：只从环境变量 SPRITE_API_KEY 读取；没有就读项目根目录的 .env（已 .gitignore，不会进 git）。
- 仓库里只有 provider.example.json 和 .env.example（都不含真实 key），别人照着填即可。
protocol 只能是 "anthropic"（Messages 接口）或 "openai"（chat/completions 接口）。
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / "provider.json"
ENV_KEY = "SPRITE_API_KEY"
PROTOCOLS = ("anthropic", "openai")
PROJECT_ROOT = Path(__file__).resolve().parents[4]                 # 仓库根目录（.env 所在）


@dataclass(frozen=True)
class Provider:
    protocol: str
    base_url: str
    model: str
    api_key: str


def _dotenv_value(name: str) -> str | None:
    """从项目根目录 .env 读一个变量；不引入第三方依赖，只支持 NAME=value 一行一个。"""
    path = PROJECT_ROOT / ".env"
    if not path.is_file(): return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key, _, value = line.partition("=")
        if key.strip() == name: return value.strip().strip('"').strip("'")
    return None


def load_api_key() -> str:
    key = os.environ.get(ENV_KEY) or _dotenv_value(ENV_KEY)
    if not key:
        raise RuntimeError(f"没有 key：请在项目根目录 .env 里写 {ENV_KEY}=你的key（模板见 .env.example）")
    return key


def load_provider(path: Path | None = None) -> Provider:
    f = path or Path(os.environ.get("SPRITE_PROVIDER", DEFAULT_FILE))
    if not f.exists():
        raise FileNotFoundError(f"没有供应商配置：请创建 {f}（模板见 sprite/proactive/provider.example.json）")
    d = json.loads(f.read_text(encoding="utf-8"))
    p = Provider(protocol=d["protocol"], base_url=d["base_url"].rstrip("/"), model=d["model"], api_key=load_api_key())
    if p.protocol not in PROTOCOLS: raise ValueError(f"protocol 只能是 {PROTOCOLS}，当前是 {p.protocol!r}")
    return p
