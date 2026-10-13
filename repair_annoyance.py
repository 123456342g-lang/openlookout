from pathlib import Path
p = Path(r"E:\OpenLookout\src\openlookout\sprite\scenarios\annoyance.py")
lines = p.read_text(encoding="utf-8").splitlines(True)
# find broken register through start of def start
i = next(n for n,l in enumerate(lines) if l.startswith("     def register") or l.startswith("    def register"))
j = next(n for n,l in enumerate(lines) if n > i and l.startswith("    def start(self, path"))
new = '''    def register(self, path: str, xml: str):
        d, n = path.rsplit("\\\\", 1); f = self.home / f"_reg_{os.getpid()}.xml"; f.write_text(xml, encoding="utf-16")
        try:
            folder = (d + "\\\\") if d else "\\\\"
            r = self._ps(("""$ErrorActionPreference="Stop"
$x=Get-Content -Raw -Encoding Unicode -LiteralPath "%s"
Register-ScheduledTask -Xml $x -TaskName "%s" -TaskPath "%s" -Force | Out-Null""" % (f, n, folder)))
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or b"").decode("utf-8", "replace")[:400]
                raise RuntimeError(msg or f"register failed rc={r.returncode}")
        finally:
            f.unlink(missing_ok=True)

'''
# Fix: use raw properly - write new as bytes carefully
new_lines = [
"    def register(self, path: str, xml: str):\n",
"        d, n = path.rsplit(\"\\\\\", 1); f = self.home / f\"_reg_{os.getpid()}.xml\"; f.write_text(xml, encoding=\"utf-16\")\n",
"        try:\n",
"            folder = (d + \"\\\\\") if d else \"\\\\\"\n",
"            r = self._ps(r'''$ErrorActionPreference=\"Stop\"\n",
"$x=Get-Content -Raw -Encoding Unicode -LiteralPath \"%s\"\n",
"Register-ScheduledTask -Xml $x -TaskName \"%s\" -TaskPath \"%s\" -Force | Out-Null''' % (f, n, folder))\n",
"            if r.returncode != 0:\n",
"                msg = (r.stderr or r.stdout or b\"\").decode(\"utf-8\", \"replace\")[:400]\n",
"                raise RuntimeError(msg or f\"register failed rc={r.returncode}\")\n",
"        finally:\n",
"            f.unlink(missing_ok=True)\n",
"\n",
]
out = lines[:i] + new_lines + lines[j:]
p.write_text("".join(out), encoding="utf-8")
import py_compile
py_compile.compile(str(p), doraise=True)
print("repaired", i, j)
