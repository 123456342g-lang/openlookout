# Windows 记录器（Python 原型）

和 `recorder/record.py` 输出同一种 `events.jsonl`，可直接喂给 `lookout/`。只用 Python 标准库，不截图，不记键盘。

```powershell
python record_win.py --seconds 600          # 录 10 分钟；不加 --seconds 就一直录，Ctrl+C 结束
```

默认监听 文档、桌面、下载 三个文件夹，可以用 `--watch 路径` 换成别的。输出在 `out\events.jsonl`。

| 事件 | 怎么来的 |
|---|---|
| `focus` | 每 0.5 秒查前台窗口（进程名 + 窗口标题），离开时写一条；chrome、msedge、soffice 等进程名换成和 Linux 版一样的 app 名 |
| `file_save` | `ReadDirectoryChangesW` 监听目录里的新建、修改、改名 |
| `file_open` | Windows 不通知“谁打开了文件”，借用系统“最近使用”文件夹里新出现的快捷方式推断，再到监听目录里找回完整路径 |
| `clipboard` | 剪贴板序号变化时读文本；复制后切到的下一个窗口记为粘贴目标 |
| `url` / `form_edit` | 和 Linux 版一样，装上 `recorder/extension` 浏览器扩展后由它上报 |

已知局限：还没在真 Windows 上跑过；`file_open` 只覆盖会写“最近使用”的程序（资源管理器、Office、WPS 大多会）；`focus` 同样是离开时才写，读取前要按 `ts` 排序。
