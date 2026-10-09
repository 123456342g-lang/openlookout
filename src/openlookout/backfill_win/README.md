# 历史回溯导入（Windows）

不再一直开着记录器。装好后**运行一次**，把电脑上已经有的使用痕迹（过去 90 天）转成 `events.jsonl`，发现流水线第一天就能在几个月的历史上找问题。

只用 Python 3.11 标准库，不需要 `pip install`。**只读**：不修改、不删除、不移动你的任何文件；**不联网、不上传**；只往输出目录里写。

## 怎么跑（PowerShell）

先把本目录放到 `E:\OpenLookout\backfill_win\`，然后：

```powershell
# 1) 先看一眼会读哪些地方（什么数据都不读）
D:\python3.11\python.exe E:\OpenLookout\backfill_win\backfill_win.py --plan

# 2) 正式导入：默认看 文档/桌面/下载，再加上 E 盘和 D 盘的项目文件夹
D:\python3.11\python.exe E:\OpenLookout\backfill_win\backfill_win.py --days 90 --roots E:\ --roots D:\项目
```

输出在 `E:\OpenLookout\data\backfill\`（C 盘快满了，所以默认放 E 盘；可以用 `--out` 换）：

| 文件 | 内容 |
|---|---|
| `events.jsonl` | 事件，按时间排好，格式和 `recorder/`、`recorder_win/` 一样 |
| `meta.json` | 运行时间、回看天数、每个来源各多少条 |
| `backfill_log.txt` | 读了哪些地方、各多少条、哪些跳过了以及为什么 |
| `content/` + `content_manifest.json` | 只有加 `--with-content` 才会有 |

一般一两分钟就跑完。浏览器开着也能读；如果某个浏览器报“读取失败”，关掉那个浏览器再跑一次。

## 读了什么

| 来源 | 位置 | 变成的事件 |
|---|---|---|
| Chrome / Edge / Brave / Tabbit 等 Chromium 内核浏览器 | `%LOCALAPPDATA%\…\User Data\<profile>\History`（自动找，Tabbit 的 `Tabbit` 和 `Tabbit Browser` 两种目录名都认）。只读 `History` 这一个文件：访问记录和下载记录 | 每次打开网页 → `focus`（app、标题、网址、停留秒数、`transition`：输入/点链接/**提交表单**等）；每次下载 → `file_create`（保存位置、来源网页、大小） |
| Firefox | `%APPDATA%\Mozilla\Firefox\Profiles\*\places.sqlite` | 同上 |
| 系统“最近使用” | `%APPDATA%\Microsoft\Windows\Recent\*.lnk`（按微软公开的快捷方式格式解析目标路径） | 最后一次打开 → `file_open`；打开时目标文件的修改时间 → `file_save` |
| Office 最近使用 | 注册表 `HKCU\Software\Microsoft\Office\<版本>\<Word/Excel/PowerPoint>\…\File MRU`（只读） | `file_open` |
| 文件夹 | 文档、桌面、下载（以注册表里的实际位置为准）、OneDrive，加上 `--roots` 指定的文件夹 | 只看 xlsx/xls/csv/docx/doc/pdf/pptx/txt/md/et/wps 等文件的**名字、创建时间、修改时间、大小** → `file_create` / `file_save` |

每条事件都带 `source` 字段（如 `backfill:chrome`、`backfill:recent`、`backfill:fs`），可以看出是从哪来的。浏览器数据库是先复制到输出目录下的 `_tmp\` 再读，读完立刻删掉。

扫文件夹时自动跳过：`node_modules`、`.git`、虚拟环境、`Windows`、`Program Files`、`AppData`、回收站、微信/QQ 的聊天文件夹、输出目录自己，以及所有隐藏目录。默认最多往下 6 层、最多看 5 万个文档类文件（`--max-depth`、`--max-files`）。

## 隐私

- **不读文件内容**（默认）。只看文件名、时间和大小。
- **永远不碰** Cookies、Login Data（保存的密码）、Web Data（自动填充）、Firefox 的 `logins.json`/`key4.db`。测试里用审计钩子确认过：这些文件连打开都没打开。
- 网址里的 `token`、`code`、`session`、`password`、`sig`、`ticket` 这类参数的值会被换成 `REDACTED`，网址里的账号密码（`user:pass@`）和 `#` 后面的部分会被去掉。想留得更少可以用 `--url-detail path`（去掉所有参数）或 `--url-detail host`（只留域名）。注意：`path` 和 `host` 会让“反复搜索同一个问题”这类发现失效。
- 不联网、不上传。输出只写在 `--out` 目录里。之后要不要把 `events.jsonl` 交给分析程序，由你自己决定。
- 文件名、网页标题和网址本身就是个人信息。分析程序发给云端模型的只有统计结果（比如“每周五去同一个网页、提交过 12 次”），不含网址、标题和文件名；每次具体发了什么，都能在 `runs/<名字>/outbound/` 里逐字查看。

### `--with-content`（默认关闭）

加上这个参数后，会把近期修改过的 xlsx/csv/txt/md/docx（单个不超过 20 MB）**复制**一份到 `content\`，最多 300 个、总共 500 MB（`--content-max-files`、`--content-max-mb`）。“解决”这一步要用到它们，比如按规律把下一份周报建好、按内容判断哪些下载是完全相同的副本。原文件不会被改动。

## 交给流水线

```bash
python3 -m lookout.run_backfill --capture /path/to/backfill --tag bf --no-llm   # 不调模型：规则判断，卡片用模板生成
python3 -m lookout.run_backfill --capture /path/to/backfill --tag bf            # 判断和写卡片调用 MiMo（2 次）
```

回溯模式下没有剪贴板和窗口切换的数据，所以会跳过“窗口来回切换”“复制粘贴”这类按分钟统计的检测器，另外加了 5 个按天和周找规律的检测器（`lookout/history.py`）：

| 检测器 | 找什么 | 自动准备好的东西 |
|---|---|---|
| `site_rhythm` | 每周固定那天去的工作网页，尤其是要提交表单的 | 按这个规律重复的日历提醒（.ics）和一键打开的快捷方式（只是提醒） |
| `recurring_files` | 按周、按月出一份、名字里带日期或编号的文件（比如 `周报_2026-10-02.xlsx`） | 日历提醒；有 `--with-content` 时，还会按命名规则把**下一份建好**（复制上一份） |
| `version_sprawl` | 同一份文档存了一堆版本，**名字叫“最终版”的反而不是最新的** | 按修改时间排好的版本清单，标出真正最新的一份 |
| `repeated_download` | 同一个文件下载了好几次 | 重复下载清单；有内容副本时，按哈希确认哪些份完全一样 |
| `last_minute` | 好几次深夜改完文件，十几分钟后就去网页上提交 | 只是一条观察，按“不打扰”规则不上清单 |

## 已知局限

- 每个文件只有**一个**修改时间，就是最后一次。中间存过几次看不到，所以“每周花多少分钟拼周报”在历史数据里算不出来。
- 浏览器的“访问”是页面加载，不等于你看了多久；Chrome 记的停留时间经常是 0。
- “最近使用”快捷方式只留了最后一次打开（Windows 上还能拿到第一次）的时间。Windows 还会定期清理这些快捷方式，太早的看不到。
- Office 的“最近使用”读的是注册表。**还没在真的 Windows 上测过**（这台测试机是 Linux）。WPS 自己的最近列表没读，WPS 打开的文件只能靠 Recent 快捷方式。
- Jump List（任务栏右键里的最近列表）格式复杂，这一版没做。
- 微信、QQ 的聊天记录是加密的，不读，聊天文件夹也默认跳过。
- 浏览器同步过来的其它设备的访问记录也会被读到。

## 测试（在 Linux 上用模拟 Windows 的假目录）

```bash
python3 backfill_win/tests/test_backfill.py      # 先造假数据（Chrome/Edge/Tabbit/Firefox 数据库、.lnk、文件），再跑一遍检查只读、隐私和输出格式
python3 -m lookout.run_backfill --capture /tmp/bf_fx/E/OpenLookout/data/backfill --tag bf_fixture_nollm --no-llm
```
