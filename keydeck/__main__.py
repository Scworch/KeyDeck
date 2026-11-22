from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path


def _is_admin() -> bool:
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _restart_as_admin() -> bool:
    """Restart the current KeyDeck invocation through the Windows UAC prompt."""
    if sys.platform != "win32":
        return True

    executable = sys.executable
    if getattr(sys, "frozen", False):
        arguments = sys.argv[1:]
        working_directory = str(Path(executable).resolve().parent)
    else:
        script = Path(sys.argv[0]).resolve()
        if script.name.casefold() == "__main__.py":
            arguments = ["-m", "keydeck", *sys.argv[1:]]
        else:
            arguments = [str(script), *sys.argv[1:]]
        working_directory = str(Path.cwd())

    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        executable,
        subprocess.list2cmdline(arguments),
        working_directory,
        1,
    )
    if result <= 32:
        print(f"Не удалось запустить KeyDeck с правами администратора (код {result}).")
        return False
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--apply-update":
        from keydeck.updates import run_updater

        raise SystemExit(run_updater(sys.argv[2:]))

    if sys.platform == "win32":
        if not _is_admin():
            if _restart_as_admin():
                raise SystemExit(0)
            raise SystemExit(1)

        try:
            from keydeck.config import load_settings
            settings = load_settings()
            if settings.high_priority:
                import ctypes
                # 0x00000080 is HIGH_PRIORITY_CLASS
                ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)
        except Exception:
            pass
    from keydeck.app import main

    raise SystemExit(main())
