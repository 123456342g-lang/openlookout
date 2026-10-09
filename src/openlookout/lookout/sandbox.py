import json, subprocess, tempfile
from pathlib import Path
from .common import ROOT

def sandbox_run(workflow, refs, params, outdir, timeout=60):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    job = outdir / "_job.json"
    job.write_text(json.dumps({"workflow": workflow, "refs": refs, "params": params, "outdir": str(outdir)}, ensure_ascii=False, default=str), encoding="utf-8")
    cmd = ["bwrap", "--ro-bind", "/", "/", "--bind", str(outdir), str(outdir), "--tmpfs", "/tmp", "--tmpfs", str(Path.home() / ".config"), "--dev", "/dev", "--proc", "/proc",
           "--unshare-net", "--unshare-pid", "--die-with-parent", "--chdir", str(ROOT), "python3", "-m", "lookout.executor", str(job)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads((outdir / "_result.json").read_text(encoding="utf-8"))
