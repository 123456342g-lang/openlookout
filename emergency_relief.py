"""Immediate reversible relief: trim working sets + suspend idle browser renderers."""
import os, sys, time
sys.path.insert(0, r'E:\OpenLookout\src\openlookout')
os.environ['SPRITE_HOME'] = r'E:\OpenLookout\sprite_home'
os.chdir(r'E:\OpenLookout\src\openlookout')

import psutil
from pathlib import Path
from sprite.winprobe import WinProbe
from sprite.procctl import JournaledController, DENY_NAMES, DENY_RE
from sprite import risk as R

home = Path(r'E:\OpenLookout\sprite_home')
R.PROC_IDLE_SCALE = 0.01  # ~9s / 18s for emergency

def free_gb():
    v = psutil.virtual_memory()
    return v.available / 2**30, v.percent

print('BEFORE free_gb=%.2f used%%=%.0f' % free_gb())

probe = WinProbe(time.time)
# two snapshots so idle_s can accumulate
p1, fg1 = probe.procs(); time.sleep(8); p2, fg2 = probe.procs()
print('foreground', fg2, 'nprocs', len(p2))

# Trim large non-denied, non-foreground processes (soft, reversible)
be = JournaledController(home, live=True, max_n=6, max_rss_mb=4096, spawn_watchdog=True,
                         extra_deny=('doubao','workbuddy','grok','sandbox-cli-gc','traesolo','verge-mihomo'),
                         log=lambda *a: print(*a))
# protect more names
extra = {'doubao','workbuddy','grok','msedgewebview2','sandbox-cli-gc','traesolo','verge-mihomo','memory compression'}
trimmed = 0
for pr in sorted(p2, key=lambda x: x.rss_mb, reverse=True)[:40]:
    n = (pr.name or '').lower()
    if n in DENY_NAMES or DENY_RE.search(n) or n in extra: continue
    if pr.foreground_tree: continue
    if pr.rss_mb < 80: continue
    try:
        if be.be.trim(pr.pid):
            trimmed += 1
            print(f'  trim {pr.pid} {n} {pr.rss_mb:.0f}MB')
    except Exception as e:
        print('  trim fail', pr.pid, e)
print('trimmed', trimmed, 'after_trim free_gb=%.2f' % free_gb()[0])

# Suspend safe browser renderers
safe = []
for pr in p2:
    rk = R.classify_proc(pr)
    if rk.level == 'safe':
        safe.append((pr, rk))
        print(f'  candidate {pr.pid} {pr.name} rss={pr.rss_mb:.0f} idle={pr.idle_s:.0f}s reason={rk.reason}')

done = []
for pr, rk in safe[:6]:
    ok = be.suspend(pr.pid, name=pr.name, rss_mb=pr.rss_mb)
    print('  suspend', pr.pid, pr.name, ok)
    if ok:
        be.trim(pr.pid); done.append(pr.pid)

print('AFTER free_gb=%.2f used%%=%.0f suspended=%s' % (*free_gb(), done))
print('journal', be.jf if be.jf.exists() else 'none')
if be.jf.exists():
    print(be.jf.read_text('utf-8')[:500])
