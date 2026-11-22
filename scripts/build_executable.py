from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BUILD_DIRS = {"keydeck", "plugins", "icons"}
EXCLUDED_PLUGIN_DIRS = {"WQS"}
ICON_FILE = ROOT / "assets" / "icon_candidates" / "exe" / "keydeck-exe-1.ico"


def is_build_source_file(relative_path: Path) -> bool:
    parts = relative_path.parts
    return (
        bool(parts)
        and parts[0] in BUILD_DIRS
        and not (
            len(parts) > 1
            and parts[0] == "plugins"
            and parts[1] in EXCLUDED_PLUGIN_DIRS
        )
    )


def main() -> int:
    if not ICON_FILE.is_file():
        raise FileNotFoundError(f"Application icon not found: {ICON_FILE}")
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
        if entry and is_build_source_file(Path(entry.decode("utf-8")))
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

        icon_path = source_root / "KeyDeck.ico"
        shutil.copy2(ICON_FILE, icon_path)
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
                "--icon",
                str(icon_path),
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
                "websocket",
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
