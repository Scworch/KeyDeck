from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from keydeck.plugin_store import parse_catalog

TAG_PATTERN = re.compile(
    r"plugin-([A-Za-z0-9][A-Za-z0-9._-]{0,99})-v(\d+(?:\.\d+){1,2})\Z"
)


def _is_private_plugin_file(relative: Path) -> bool:
    parts = tuple(part.casefold() for part in relative.parts)
    filename = relative.name.casefold()
    return (
        any(part in {"cache", "__pycache__", ".git"} for part in parts)
        or ("settings" in filename and filename.endswith(".json"))
        or filename.endswith(".log")
    )


def package_plugin_release(
    tag: str,
    output_dir: Path,
    root: Path = ROOT,
) -> tuple[Path, Path]:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"Invalid plugin release tag: {tag}")
    plugin_id, version = match.groups()
    catalog = parse_catalog((root / "plugins" / "catalog.json").read_bytes())
    entry = next((item for item in catalog if item.plugin_id == plugin_id), None)
    if entry is None or entry.version != version:
        raise ValueError(
            "Plugin release tag must match the plugin's current catalog ID and version"
        )

    plugin_dir = root / "plugins" / plugin_id
    manifest_path = plugin_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Plugin {plugin_id} has no valid manifest") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("id") != entry.plugin_id
        or manifest.get("version") != entry.version
        or manifest.get("min_keydeck_version") != entry.min_keydeck_version
        or manifest.get("max_keydeck_version") != entry.max_keydeck_version
        or tuple(manifest.get("permissions", [])) != entry.permissions
        or tuple(manifest.get("action_prefixes", [])) != entry.action_prefixes
    ):
        raise ValueError("Plugin manifest does not match the catalog release metadata")

    listing = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "--", f"plugins/{plugin_id}"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    tracked_paths = [
        Path(raw.decode("utf-8"))
        for raw in listing.split(b"\0")
        if raw
    ]
    package_files = [
        path
        for path in tracked_paths
        if path.parts[:2] == ("plugins", plugin_id)
        and not _is_private_plugin_file(Path(*path.parts[2:]))
        and (root / path).is_file()
        and not (root / path).is_symlink()
    ]
    entry_path = Path(manifest.get("entry", "plugin.py"))
    relative_paths = {Path(*path.parts[2:]) for path in package_files}
    if Path("manifest.json") not in relative_paths:
        raise ValueError("Plugin manifest is not tracked by Git")
    if entry_path not in relative_paths:
        raise ValueError("Plugin entry file is not tracked by Git")
    if Path("..") in entry_path.parts or entry_path.is_absolute():
        raise ValueError("Plugin entry file must remain inside the plugin folder")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / entry.archive_name
    checksum_path = output_dir / "SHA256SUMS.txt"
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(package_files):
            relative = Path(*path.parts[2:])
            archive.write(root / path, relative.as_posix())
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="ascii",
    )
    return archive_path, checksum_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Plugin release tag: plugin-<id>-v<version>")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Directory for release assets (defaults to dist/)",
    )
    arguments = parser.parse_args(argv)
    archive_path, checksum_path = package_plugin_release(
        arguments.tag,
        arguments.output_dir,
    )
    print(archive_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
