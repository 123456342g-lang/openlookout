# OpenLookout 小精灵

**辅助型伙伴。** 它看着你此刻的屏幕，在你卡住的时候开口帮忙，其余时间安静陪着。方向盘在你手里：它主动看、主动说，改你的电脑之前会问你；只有临时文件、缓存、回收站这种收进隔离区、随时能还原的清理，做完再告诉你。

**An assistive partner.** It watches the screen you are on right now and speaks up when you are stuck. Otherwise it stays quiet. You stay in charge: it may look and it may talk, and it asks before it changes the machine. Temp files, caches, and the recycle bin are the exception — those go into a quarantine it can restore, and it tells you afterwards.

它不是整机管家，也不做自由探索。系统维护、扫全盘历史、替你写报告，都不是现在要试的东西。

## 五分钟跑起来（Windows）

需要 Python 3.11、一块能截屏的桌面。不需要 Docker，也不需要安装 Claude Code。

```powershell
copy .env.example .env
cd src\openlookout
python -m pip install pillow psutil jsonschema certifi -r requirements-proactive.txt
copy sprite\proactive\provider.example.json sprite\proactive\provider.json
```

编辑两处，不要把密钥提交进 git：

- 仓库根目录 `.env`：`SPRITE_API_KEY=你的key`，再加一行 `OPENLOOKOUT_BACKEND=direct`。
- `src\openlookout\sprite\proactive\provider.json`：填你的 Anthropic 兼容接口地址和模型名（这个文件不含 key）。

然后，仍在 `src\openlookout`：

```powershell
python -m sprite.proactive.live
```

小精灵出现在桌面右下角。点它就能聊天。屏幕上的事卡住了，它会自己开口；你点「好的」它才动手，气泡上可以撤销。

## 后端（都可选，没有硬锁定）

| 方式 | 什么时候用 |
|---|---|
| `OPENLOOKOUT_BACKEND=direct` | **推荐的第一次运行。** 直接请求 `provider.json` 里的接口。不起 Claude Code，不起 Docker。 |
| 本机已有 `claude` 命令、且不设上面的变量 | 走本机 Claude Code 作为传输通道。模型仍是你在环境里配置的那一个。 |
| Docker 里的 Claude player 镜像 | 旧的可选路径，见 `AGENTS.md`。第一次试用不必构建。 |

截图只在你的电脑和你配置的模型服务之间传输。`.env`、`provider.json`、`sprite_home/` 不进 git。

## 仓库里还有什么

`src/openlookout/lookout/` 和根目录的 `record_win.py` 是更早的研究原型（行为痕迹、本机记录器）。公开试用请从上面的小精灵开始。贡献者和架构说明见 [AGENTS.md](AGENTS.md)。

## 协作

改动走分支和 Pull Request，不要直接推 `main`。一个任务一个分支。`third_party/` 不在这个仓库里，也不是运行依赖，见 [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)。

许可证：MIT（本文件树；内含的 VISTA 代码自带它自己的 MIT 声明，见 `src/openlookout/vista/LICENSE.txt`）。
