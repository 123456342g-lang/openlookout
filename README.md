# OpenLookout 小精灵

**辅助型伙伴。** 它看着你此刻的屏幕，在你卡住的时候开口帮忙，其余时间安静陪着。方向盘在你手里：它主动看、主动说，改你的电脑之前会问你；只有临时文件、缓存、回收站这种收进隔离区、随时能还原的清理，做完再告诉你。

**An assistive partner.** It watches the screen you are on right now and speaks up when you are stuck. Otherwise it stays quiet. You stay in charge: it may look and it may talk, and it asks before it changes the machine. Temp files, caches, and the recycle bin are the exception — those go into a quarantine it can restore, and it tells you afterwards.

English: [README_en.md](README_en.md).

它不是整机管家，也不做自由探索。系统维护、扫全盘历史、替你写报告，都不是现在要试的东西。仓库里没有截图。

## 安装（Windows）

需要 Python 3.11 或更新，以及一块能截屏的桌面。在仓库根目录双击或运行：

```bat
install.bat
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

脚本会检查 Python 版本，安装 `pillow`、`psutil`、`jsonschema`、`certifi` 和 `requirements-proactive.txt`，再尝试安装可选的 `pystray`。`pystray` 装不上不影响继续。接着运行首次向导；向导没写完配置就不会启动小精灵。

向导（也可单独跑）会问协议、接口地址、模型名和 key，并写入：

- `src/openlookout/sprite/proactive/provider.json`（不含 key）
- 仓库根目录 `.env` 里的 `SPRITE_API_KEY`

没有终端时，向导只打印一句说明并以退出码 2 结束，不会启动 Claude Code。

手工等价步骤，仍在仓库根目录：

```powershell
cd src\openlookout
python -m pip install pillow psutil jsonschema certifi -r requirements-proactive.txt
python -m sprite.proactive.first_run
python -m sprite.proactive.live
```

小精灵出现在桌面右下角。点它就能聊天。

## 模型怎么接

默认是直连 HTTP，读 `provider.json`。不需要设置 `OPENLOOKOUT_BACKEND=direct`，也不需要 Docker 或 Claude Code。

`provider.json` 只读取这三个字段，多出来的键会被忽略。`provider.example.json` 里的 `examples` 数组只是例子，加载器不会从里面挑一项：

| 协议 | 请求 | 例子 |
|---|---|---|
| `anthropic` | `{base}/v1/messages` | 任何 Anthropic Messages 兼容地址。基址已含 `/v1` 时不会再加一层。 |
| `openai` | `{base}/v1/chat/completions` | OpenAI `https://api.openai.com/v1`、DeepSeek `https://api.deepseek.com/v1`（模型名用服务商公开的名字，例如 `deepseek-chat`）、本机 Ollama `http://localhost:11434/v1` |

Ollama 常常不看 Authorization 头，但 `SPRITE_API_KEY` 仍必须非空。本地可以填占位符 `ollama`。缺 key 时显示的是首次运行那一句，不是另一套空 key 异常。

本机模型能不能看图、能不能调用工具，取决于那个模型本身。客户端等一整份 JSON，不发送 `stream`。只提供 SSE 的服务会失败。这里没有接真实的 Ollama、OpenAI 或 DeepSeek 做验证，协议测试用的是模拟 HTTP。

Claude Code 是可选项：`OPENLOOKOUT_BACKEND=claude`（`host` 是同一条路的别名）。Claude 起不来就报错退出，不会改走直连。直连缺配置也不会改走 Claude。

## 暂停、退出、撤销

在小精灵上右键或中键：暂停、撤销、退出。暂停时大脑和规则进程跳过这一轮。退出会写一个 `QUIT` 文件，监督进程停下，并且不再把子进程拉起来。

系统托盘菜单只在 `pystray` 能导入时出现。导入失败时窗口照常开，右键菜单仍在。托盘没有在一台真实的 Windows 桌面上验证过。

## 规则引擎

监督进程除了大脑、窗口和操作记录器，还会拉起规则进程。它用已经测过的资源场景（内存压力、挂起、隔离可还原的缓存），不调用模型。引擎自己判定为安全、可撤回的动作会先做再在气泡里说明，并带上撤销；高风险或不能撤回的动作会跳过。点「好的」才执行的提议仍然只走模型那条 offer。

## 费用

一轮仍然要等画面变化、新的反馈，或心跳。发出去的图如果长边超过 768 像素，会先缩小成 JPEG。同一轮后面的请求，如果屏幕没变，就不再附上整张截图；工具返回的小图裁块会留下。每一轮默认最多 4 次 HTTP（`OPENLOOKOUT_MAX_CALLS`，限制在 1 到 8）。

## 配置

| 名字 | 作用 |
|---|---|
| `OPENLOOKOUT_BACKEND` | 空或 `direct`：直连。`claude` / `host`：本机 Claude Code。不认识的值仍走直连。 |
| `OPENLOOKOUT_MODEL` | 覆盖 `provider.json` 的 `model`。空则用文件里的名字。 |
| `OPENLOOKOUT_LANG` | `zh` 或 `en`。空则跟 Windows 显示语言：`zh*` 中文，其余英文。 |
| `OPENLOOKOUT_MAX_CALLS` | 每轮 HTTP 上限，默认 4，夹在 1 到 8。 |
| `SPRITE_API_KEY` | 必填、非空。Ollama 可用占位符 `ollama`。 |
| `provider.json` | `protocol`、`base_url`、`model`。其它键忽略。 |

界面文字在用到的时候才翻译。监督日志仍是中文。

## 隐私

截图和一起送出的文字只发往 `provider.json` 里的那个地址。`sprite_home`、`.env`、`provider.json` 留在本机，并且已在 `.gitignore` 里。这个仓库不包含截图。

## 卸载

用菜单退出，或结束 `python -m sprite.proactive.live`。然后删掉运行数据、`.env` 和 `provider.json`：

- 设了 `SPRITE_HOME` 就删那个目录
- Windows 默认是 `%LOCALAPPDATA%\OpenLookout\sprite_home`
- 其它系统默认是 `~/.openlookout/sprite_home`
- 仓库根目录的 `.env`
- `src/openlookout/sprite/proactive/provider.json`

## 仓库里还有什么

`src/openlookout/lookout/` 和根目录的 `record_win.py` 是更早的研究原型。公开试用请从上面的小精灵开始。贡献者和架构说明见 [AGENTS.md](AGENTS.md)。

改动走分支和 Pull Request，不要直接推 `main`。`third_party/` 不在这个仓库里，也不是运行依赖，见 [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)。

许可证：MIT（本文件树；内含的 VISTA 代码自带它自己的 MIT 声明，见 `src/openlookout/vista/LICENSE.txt`）。
