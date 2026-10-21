"""System-tray icon for pause, undo, and quit.

The sprite window always has the same menu on right-click. A tray icon is
started only when pystray can be imported and its backend loads. If it cannot,
the right-click menu is the control that remains.
"""
from __future__ import annotations

import threading

from PIL import Image


def try_start_tray(items, on_action) -> object | None:
    """Start a tray icon. ``items`` is a zero-arg callable returning menu_spec.

    Returns the icon, or None when pystray is missing or the platform backend
    refuses to start. Failure here must not stop the window.
    """
    try:
        import pystray
    except ImportError:
        return None
    try:
        image = Image.new("RGB", (64, 64), "#2a9d8f")

        def _text(index):
            return lambda _item: items()[index][1]

        def _run(index):
            return lambda _icon, _item: on_action(items()[index][0])

        menu = pystray.Menu(
            pystray.MenuItem(_text(0), _run(0)),
            pystray.MenuItem(_text(1), _run(1)),
            pystray.MenuItem(_text(2), _run(2)),
        )
        icon = pystray.Icon("openlookout", image, "OpenLookout", menu)
        threading.Thread(target=icon.run, name="openlookout-tray", daemon=True).start()
        return icon
    except Exception as exc:
        print(f"[tray] unavailable: {type(exc).__name__}", flush=True)
        return None
