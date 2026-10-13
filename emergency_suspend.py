import os, sys, json, time
sys.path.insert(0, r'E:\OpenLookout\src\openlookout')
os.environ['SPRITE_HOME'] = r'E:\OpenLookout\sprite_home'
os.chdir(r'E:\OpenLookout\src\openlookout')

from sprite.winprobe import WinProbe
import sprite.procctl as procctl
import inspect

probe = WinProbe()
mem = probe.memory() if hasattr(probe, 'memory') else None
print('MEM', mem)

# list probe attrs
print('WinProbe methods', [m for m in dir(probe) if not m.startswith('_')])

# try get processes
procs = None
for name in ('processes', 'list_processes', 'snapshot', 'procs'):
    if hasattr(probe, name):
        fn = getattr(probe, name)
        procs = fn() if callable(fn) else fn
        print('got procs via', name, 'n=', len(procs) if procs is not None else None)
        break

if procs:
    def rss_of(p):
        for k in ('rss_mb', 'rss_mib', 'working_set_mb'):
            if hasattr(p, k) and getattr(p, k) is not None:
                return float(getattr(p, k))
            if isinstance(p, dict) and p.get(k) is not None:
                return float(p[k])
        for k in ('rss', 'working_set'):
            v = getattr(p, k, None) if not isinstance(p, dict) else p.get(k)
            if v: return float(v) / (1024*1024)
        return 0.0
    def field(p, *keys):
        for k in keys:
            if isinstance(p, dict) and k in p: return p[k]
            if hasattr(p, k): return getattr(p, k)
        return None
    ranked = sorted(procs, key=rss_of, reverse=True)
    for p in ranked[:20]:
        print(f"  pid={field(p,'pid')} name={field(p,'name','exe')} rss={rss_of(p):.0f} idle={field(p,'idle_sec','idle_s','idle')} fg={field(p,'foreground','is_foreground','is_fg')} title={(str(field(p,'title','window_title') or ''))[:50]!r}")

print('procctl exports', [m for m in dir(procctl) if not m.startswith('_')])
# Find controller class
for name in dir(procctl):
    obj = getattr(procctl, name)
    if inspect.isclass(obj):
        print('class', name, 'init', inspect.signature(obj.__init__) if hasattr(obj,'__init__') else None)
        print('  methods', [m for m in dir(obj) if not m.startswith('_')])
