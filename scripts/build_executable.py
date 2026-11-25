from __future__ import annotations

import argparse
from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BUILD_DIRS = {"keydeck", "plugins", "icons"}
ICON_FILE = ROOT / "assets" / "icon_candidates" / "exe" / "keydeck-exe-1.ico"


def is_build_source_file(relative_path: Path) -> bool:
    parts = relative_path.parts
    if parts and parts[0] == "plugins":
        return relative_path == Path("plugins") / "catalog.json"
    return (
        bool(parts)
        and parts[0] in BUILD_DIRS
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Directory for the built executable (defaults to dist/)",
    )
    arguments = parser.parse_args(argv)
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
                str(arguments.output_dir),
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
                f"{source_root / 'plugins' / 'catalog.json'};plugins",
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
