from __future__ import annotations

import sys


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--apply-update":
        from keydeck.updates import run_updater

        raise SystemExit(run_updater(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--uninstall":
        from keydeck.uninstall import run_uninstaller

        raise SystemExit(run_uninstaller(sys.argv[2:]))

    if sys.platform == "win32":
        from keydeck.admin import is_admin, restart_as_admin
        from keydeck.config import load_settings

        settings = load_settings()
        needs_admin = settings.run_as_admin or "--retry-autostart" in sys.argv
        if needs_admin and not is_admin():
            if restart_as_admin():
                raise SystemExit(0)
            raise SystemExit(1)

        if settings.high_priority:
            # 0x00000080 is HIGH_PRIORITY_CLASS
            import ctypes

            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(),
                0x00000080,
            )
    from keydeck.app import main

    raise SystemExit(main())
