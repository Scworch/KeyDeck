from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path


def is_admin() -> bool:
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def restart_as_admin(extra_arguments: list[str] | None = None) -> bool:
    if sys.platform != "win32":
        return False

    executable = sys.executable
    if getattr(sys, "frozen", False):
        arguments = [*sys.argv[1:], *(extra_arguments or [])]
        working_directory = str(Path(executable).resolve().parent)
    else:
        script = Path(sys.argv[0]).resolve()
        if script.name.casefold() == "__main__.py":
            arguments = ["-m", "keydeck", *sys.argv[1:], *(extra_arguments or [])]
        else:
            arguments = [str(script), *sys.argv[1:], *(extra_arguments or [])]
        working_directory = str(Path.cwd())

    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        executable,
        subprocess.list2cmdline(arguments),
        working_directory,
        1,
    )
    return result > 32
