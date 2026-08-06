from __future__ import annotations

import sys

from keydeck.app import main


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            import ctypes
            # 0x00000080 is HIGH_PRIORITY_CLASS
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)
        except Exception:
            pass
    raise SystemExit(main())
