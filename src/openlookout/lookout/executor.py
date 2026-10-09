"""在 bubblewrap 沙箱里执行一个工作流：无网络；用户文件只读；只能写指定的输出目录。
用法（由 sandbox_run 调用）：python3 -m lookout.executor job.json"""
import json, sys
from .blocks import run_workflow

if __name__ == "__main__":
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    vals, files, trace = run_workflow(job["workflow"], job["refs"], job["params"], job["outdir"])
    json.dump({"vals": vals, "files": files, "trace": trace}, open(job["outdir"] + "/_result.json", "w", encoding="utf-8"), ensure_ascii=False, default=str)
