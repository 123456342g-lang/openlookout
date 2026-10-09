# 记录器（Python 原型，Linux/X11）

真实记录三类事件，格式和 `capture/events.jsonl` 一样，可直接喂给 `lookout/`。

```
python3 recorder/record.py --watch ~/文档 --watch ~/下载 --out recorder/out/events.jsonl
```

依赖：Python 3 标准库，加上系统命令 `xprop`、`xclip`。不截图，不记键盘。

| 事件 | 怎么来的 | 字段 |
|---|---|---|
| `focus` | 每 0.5 秒查一次当前窗口，离开时写一条 | app（WM_CLASS）、title、dur_s |
| `file_open` / `file_save` | inotify 监听 `--watch` 目录（含子目录），同一文件 5 秒内去重 | path（相对 `--home` 的上一级）、app（当时的焦点窗口） |
| `clipboard` | 剪贴板内容变化；切到的下一个窗口记为粘贴目标 | src_app/src_title、dst_app/dst_title、len、hash；`--keep-text` 才写原文 |

已在本机 X 桌面用 LibreOffice Calc 实测（2026-10-09）。已知局限：
- `focus` 在离开窗口时才写，所以文件里时间不是严格递增，读取前要按 `ts` 排序。
- inotify 不知道是哪个进程改的文件，`app` 只是当时的焦点窗口，可能不准。
- 只支持 X11，Wayland 拿不到当前窗口。

## 浏览器扩展（`recorder/extension/`）

补上 `focus` 里的 `url` 和 `form_edit` 事件。记录器默认在 `127.0.0.1:8765` 收扩展上报（`--ext-port 0` 关闭）。

- 网址：切换标签页、页面加载、窗口切回来时上报，按标题对到当前浏览器窗口。
- 表单：只记「哪个字段、打字还是粘贴」，不记填了什么；密码框和隐藏字段不记。在同一窗口里粘贴时，剪贴板事件的粘贴目标会改成当前窗口。
- 安装：Chrome/Edge 打开扩展管理页，开发者模式里选「加载已解压的扩展程序」，选这个目录。
- 已用 Chromium 在本机实测（2026-10-09）：网址、打字、粘贴三种事件都对，密码框没被记录。正式版 Google Chrome 不认 `--load-extension` 启动参数，只能手动加载。
