# third_party

`third_party/rea` 曾经是磁盘上的一份嵌套 git 仓库（约 34MB）。它不是 OpenLookout 的运行依赖：代码里没有 import 它，公开克隆里也不包含它。

决定（公开发布）：

- 继续放在仓库外面。根目录 `.gitignore` 忽略整个 `third_party/`。
- 不做成 submodule。没有上游需要跟着小精灵一起克隆。
- 本机如果还留着那份目录，可以自行删除；删不删不影响 `python -m sprite.proactive.live`。
