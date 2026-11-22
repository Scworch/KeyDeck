from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BUILD_DIRS = {"keydeck", "plugins", "icons"}


def main() -> int:
    pythonnet_spec = find_spec("pythonnet")
    if pythonnet_spec is None or not pythonnet_spec.submodule_search_locations:
        raise RuntimeError("pythonnet must be installed before building the executable")
    pythonnet_hooks = Path(next(iter(pythonnet_spec.submodule_search_locations))) / "_pyinstaller"

    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    tracked_source_files = [
        Path(entry.decode("utf-8"))
        for entry in listing.split(b"\0")
        if entry and Path(entry.decode("utf-8")).parts[0] in BUILD_DIRS
    ]

    with tempfile.TemporaryDirectory(prefix="KeyDeck-build-") as temporary:
        temporary_root = Path(temporary)
        source_root = temporary_root / "source"
        for relative_path in tracked_source_files:
            source = ROOT / relative_path
            if not source.is_file():
                continue
            destination = source_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        executable = subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--name",
                "KeyDeck",
                "--paths",
                str(source_root),
                "--additional-hooks-dir",
                str(pythonnet_hooks),
                "--distpath",
                str(ROOT / "dist"),
                "--workpath",
                str(temporary_root / "work"),
                "--specpath",
                str(temporary_root),
                "--hidden-import",
                "psutil",
                "--hidden-import",
                "keyboard",
                "--hidden-import",
                "clr",
                "--hidden-import",
                "clr_loader",
                "--hidden-import",
                "pycaw",
                "--hidden-import",
                "comtypes",
                "--collect-all",
                "pycaw",
                "--collect-all",
                "comtypes",
                "--collect-all",
                "clr_loader",
                "--add-data",
                f"{source_root / 'plugins'};plugins",
                "--add-data",
                f"{source_root / 'icons'};icons",
                str(source_root / "keydeck" / "__main__.py"),
            ],
            cwd=source_root,
            check=False,
        )
    return executable.returncode


if __name__ == "__main__":
    raise SystemExit(main())
