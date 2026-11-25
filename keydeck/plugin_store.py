from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from typing import Any

from keydeck import __version__

CATALOG_URL = (
    "https://raw.githubusercontent.com/Scworch/KeyDeck/main/plugins/catalog.json"
)
GITHUB_RELEASE_BASE = (
    "https://github.com/Scworch/KeyDeck/releases/download"
)
REQUEST_TIMEOUT = 15
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_FILES = 2000
ALLOWED_PERMISSIONS = frozenset(
    {
        "filesystem",
        "network",
        "plugin_control",
        "process",
        "system_audio",
        "system_input",
        "system_network",
        "system_settings",
    }
)
_PLUGIN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+){1,2}\Z")
_CHECKSUM_PATTERN = re.compile(r"([0-9a-fA-F]{64})\s+\*?(.+)\Z")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True)
class PluginCatalogEntry:
    plugin_id: str
    name: str
    version: str
    description: str
    min_keydeck_version: str
    permissions: tuple[str, ...]
    max_keydeck_version: str | None = None
    action_prefixes: tuple[str, ...] = ()

    @property
    def release_tag(self) -> str:
        return f"plugin-{self.plugin_id}-v{self.version}"

    @property
    def archive_name(self) -> str:
        return f"KeyDeckPlugin-{self.plugin_id}-{self.version}.zip"

    @property
    def archive_url(self) -> str:
        return f"{GITHUB_RELEASE_BASE}/{self.release_tag}/{self.archive_name}"

    @property
    def checksum_url(self) -> str:
        return f"{GITHUB_RELEASE_BASE}/{self.release_tag}/SHA256SUMS.txt"


def version_key(version: str) -> tuple[int, ...]:
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Unsupported version format: {version}")
    parts = tuple(int(part) for part in version.split("."))
    return parts + (0,) * (3 - len(parts))


def parse_catalog(raw: bytes | str) -> list[PluginCatalogEntry]:
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Plugin catalog is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported plugin catalog schema")
    raw_plugins = data.get("plugins")
    if not isinstance(raw_plugins, list):
        raise ValueError("Plugin catalog must contain a plugins list")

    entries: list[PluginCatalogEntry] = []
    seen_ids: set[str] = set()
    seen_action_prefixes: set[str] = set()
    if len(raw_plugins) > 1000:
        raise ValueError("Plugin catalog contains too many entries")
    for item in raw_plugins:
        if not isinstance(item, dict):
            raise ValueError("Plugin catalog entries must be objects")
        plugin_id = item.get("id")
        name = item.get("name")
        description = item.get("description")
        version = item.get("version")
        minimum = item.get("min_keydeck_version")
        maximum = item.get("max_keydeck_version")
        permissions = item.get("permissions")
        action_prefixes = item.get("action_prefixes", [])
        if not isinstance(plugin_id, str) or not _PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise ValueError("Plugin catalog contains an invalid plugin ID")
        if plugin_id.casefold() in seen_ids:
            raise ValueError(f"Plugin catalog contains duplicate ID: {plugin_id}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Plugin {plugin_id} has no display name")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Plugin {plugin_id} has no description")
        version_key(version)
        version_key(minimum)
        if maximum is not None:
            version_key(maximum)
            if version_key(maximum) < version_key(minimum):
                raise ValueError(f"Plugin {plugin_id} has an invalid compatibility range")
        if not isinstance(permissions, list) or any(
            not isinstance(permission, str)
            or permission not in ALLOWED_PERMISSIONS
            for permission in permissions
        ):
            raise ValueError(f"Plugin {plugin_id} declares invalid permissions")
        if len(set(permissions)) != len(permissions):
            raise ValueError(f"Plugin {plugin_id} repeats a permission")
        if not isinstance(action_prefixes, list) or any(
            not isinstance(prefix, str)
            or not _PLUGIN_ID_PATTERN.fullmatch(prefix)
            for prefix in action_prefixes
        ):
            raise ValueError(f"Plugin {plugin_id} has invalid action prefixes")
        if len({prefix.casefold() for prefix in action_prefixes}) != len(action_prefixes):
            raise ValueError(f"Plugin {plugin_id} repeats an action prefix")
        for prefix in (plugin_id, *action_prefixes):
            normalized_prefix = prefix.casefold()
            if normalized_prefix in seen_action_prefixes:
                raise ValueError(f"Plugin catalog repeats action prefix: {prefix}")
            seen_action_prefixes.add(normalized_prefix)
        entries.append(
            PluginCatalogEntry(
                plugin_id=plugin_id,
                name=name.strip(),
                version=version,
                description=description.strip(),
                min_keydeck_version=minimum,
                permissions=tuple(permissions),
                max_keydeck_version=maximum,
                action_prefixes=tuple(action_prefixes),
            )
        )
        seen_ids.add(plugin_id.casefold())
    return entries


def _read_bounded(response: Any, limit: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise ValueError(f"{label} exceeds the permitted size")
        chunks.append(chunk)


def _open_url(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "KeyDeck-Plugin-Library",
        },
    )
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)


class PluginStore:
    def __init__(
        self,
        installed_plugins_dir: Path,
        backup_dir: Path,
        catalog_file: Path,
        keydeck_version: str = __version__,
    ) -> None:
        self.installed_plugins_dir = installed_plugins_dir
        self.backup_dir = backup_dir
        self.catalog_file = catalog_file
        self.keydeck_version = keydeck_version

    def bundled_catalog(self) -> list[PluginCatalogEntry]:
        try:
            raw = self.catalog_file.read_bytes()
        except OSError as exc:
            raise OSError(f"Could not read the bundled plugin catalog: {exc}") from exc
        return parse_catalog(raw)

    def retired_plugin_ids(self) -> set[str]:
        try:
            data = json.loads(self.catalog_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"Plugin catalog is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Plugin catalog must be an object")
        raw_ids = data.get("retired_plugins", [])
        if not isinstance(raw_ids, list):
            raise ValueError("Plugin catalog retired_plugins must be a list")
        retired: set[str] = set()
        for plugin_id in raw_ids:
            self._validate_plugin_id(plugin_id)
            if plugin_id in retired:
                raise ValueError(f"Plugin catalog repeats retired plugin ID: {plugin_id}")
            retired.add(plugin_id)
        return retired

    def fetch_catalog(self) -> list[PluginCatalogEntry]:
        try:
            with _open_url(CATALOG_URL) as response:
                raw = _read_bounded(response, MAX_CATALOG_BYTES, "Plugin catalog")
        except (http.client.HTTPException, OSError, urllib.error.URLError) as exc:
            raise OSError(f"Could not download plugin catalog: {exc}") from exc
        return parse_catalog(raw)

    def installed_version(self, plugin_id: str) -> str | None:
        plugin_dir = self._plugin_path(plugin_id)
        if not plugin_dir.is_dir() or plugin_dir.is_symlink():
            return None
        manifest_path = plugin_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"Installed plugin {plugin_id} has an invalid manifest") from exc
        if not isinstance(manifest, dict) or manifest.get("id") != plugin_id:
            raise ValueError(f"Installed plugin folder does not match ID {plugin_id}")
        version = manifest.get("version")
        if version is None:
            return "0.0.0"
        version_key(version)
        return version

    def is_installed(self, plugin_id: str) -> bool:
        plugin_dir = self._plugin_path(plugin_id)
        return plugin_dir.is_dir() and not plugin_dir.is_symlink()

    def has_rollback(self, plugin_id: str) -> bool:
        self._validate_plugin_id(plugin_id)
        backup = self.backup_dir / plugin_id
        return backup.is_dir() and not backup.is_symlink()

    def install(self, entry: PluginCatalogEntry, *, consent: bool = False) -> str:
        if not consent:
            raise PermissionError("Plugin installation requires explicit user consent")
        self._validate_entry(entry)
        active = self._plugin_path(entry.plugin_id)
        installed_version = self.installed_version(entry.plugin_id)
        if active.exists() and installed_version is None:
            raise ValueError(f"Plugin install path for {entry.plugin_id} is not a directory")
        if installed_version is not None and version_key(entry.version) <= version_key(
            installed_version
        ):
            raise ValueError(
                f"{entry.name} {installed_version} is already installed; "
                "the library only installs newer versions"
            )
        self.installed_plugins_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if self.installed_plugins_dir.is_symlink() or self.backup_dir.is_symlink():
            raise ValueError("Plugin storage directories must not be symbolic links")
        with tempfile.TemporaryDirectory(
            prefix=f"KeyDeck-plugin-{entry.plugin_id}-",
            dir=self.installed_plugins_dir,
        ) as temporary:
            staging_root = Path(temporary)
            archive = self._download_archive(entry)
            extracted = staging_root / "plugin"
            extracted.mkdir()
            self._extract_and_validate(archive, extracted, entry)
            backup = self.backup_dir / entry.plugin_id
            backup_staging = self.backup_dir / f".{entry.plugin_id}.previous"
            self._remove_directory(backup_staging)
            moved_active = False
            try:
                if active.exists():
                    if active.is_symlink():
                        raise ValueError("Plugin install path must not be a symbolic link")
                    self._remove_directory(backup)
                    os.replace(active, backup_staging)
                    moved_active = True
                os.replace(extracted, active)
                if moved_active:
                    os.replace(backup_staging, backup)
            except OSError:
                if active.exists() and moved_active:
                    self._remove_directory(active)
                if moved_active and backup_staging.exists():
                    os.replace(backup_staging, active)
                raise
        return entry.version

    def uninstall(self, plugin_id: str, *, allow_missing: bool = False) -> None:
        plugin_dir = self._plugin_path(plugin_id)
        if not plugin_dir.exists():
            if not allow_missing:
                raise FileNotFoundError(f"Plugin {plugin_id} is not installed")
            self._remove_directory(self.backup_dir / plugin_id)
            return
        if plugin_dir.is_symlink() or not plugin_dir.is_dir():
            raise ValueError("Plugin install path is not a regular directory")
        manifest_path = plugin_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = self._read_manifest(manifest_path)
            except ValueError:
                manifest = {}
            manifest_id = manifest.get("id")
            if manifest_id is not None and manifest_id != plugin_id:
                raise ValueError("Plugin install path contains another plugin")
        self._remove_directory(plugin_dir)
        self._remove_directory(self.backup_dir / plugin_id)

    def rollback(self, plugin_id: str) -> str:
        active = self._plugin_path(plugin_id)
        backup = self.backup_dir / plugin_id
        if not active.is_dir() or active.is_symlink():
            raise FileNotFoundError(f"Plugin {plugin_id} is not installed")
        if not backup.is_dir() or backup.is_symlink():
            raise FileNotFoundError(f"No previous version of {plugin_id} is available")
        current_version = self.installed_version(plugin_id)
        previous_manifest = self._read_manifest(backup / "manifest.json")
        if previous_manifest.get("id") != plugin_id:
            raise ValueError("Plugin rollback data does not match the selected plugin")
        previous_version = previous_manifest.get("version", "0.0.0")
        version_key(previous_version)
        minimum = previous_manifest.get("min_keydeck_version", "0.0.0")
        if version_key(minimum) > version_key(self.keydeck_version):
            raise ValueError("Previous plugin version requires a newer KeyDeck")
        maximum = previous_manifest.get("max_keydeck_version")
        if maximum is not None and version_key(maximum) < version_key(self.keydeck_version):
            raise ValueError("Previous plugin version does not support this KeyDeck version")
        self._validate_relative_file(backup, previous_manifest.get("entry", "plugin.py"))
        if current_version == previous_version:
            raise RuntimeError("Rollback would not change the installed plugin version")
        temporary = self.installed_plugins_dir / f".{plugin_id}.rollback"
        self._remove_directory(temporary)
        os.replace(active, temporary)
        try:
            os.replace(backup, active)
            os.replace(temporary, backup)
        except OSError:
            if temporary.exists():
                if active.exists() and not backup.exists():
                    os.replace(active, backup)
                os.replace(temporary, active)
            raise
        return previous_version

    def _download_archive(self, entry: PluginCatalogEntry) -> bytes:
        if not entry.archive_url.startswith(
            f"{GITHUB_RELEASE_BASE}/{entry.release_tag}/"
        ) or not entry.checksum_url.startswith(
            f"{GITHUB_RELEASE_BASE}/{entry.release_tag}/"
        ):
            raise ValueError("Plugin downloads must use the official KeyDeck release")
        try:
            with _open_url(entry.checksum_url) as response:
                checksum_data = _read_bounded(response, 64 * 1024, "Plugin checksum")
            with _open_url(entry.archive_url) as response:
                archive = _read_bounded(response, MAX_ARCHIVE_BYTES, "Plugin archive")
        except (http.client.HTTPException, OSError, urllib.error.URLError) as exc:
            raise OSError(f"Could not download {entry.name}: {exc}") from exc

        expected_digest = None
        try:
            checksum_text = checksum_data.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("Plugin checksum file is not ASCII") from exc
        for line in checksum_text.splitlines():
            match = _CHECKSUM_PATTERN.fullmatch(line.strip())
            if match and Path(match.group(2)).name == entry.archive_name:
                expected_digest = match.group(1).lower()
                break
        if expected_digest is None:
            raise ValueError("Plugin checksum does not list the expected archive")
        if hashlib.sha256(archive).hexdigest() != expected_digest:
            raise ValueError("Plugin archive failed its SHA-256 check")
        return archive

    def _extract_and_validate(
        self,
        archive: bytes,
        destination: Path,
        entry: PluginCatalogEntry,
    ) -> None:
        try:
            package = zipfile.ZipFile(io.BytesIO(archive))
        except (OSError, EOFError, zipfile.BadZipFile) as exc:
            raise ValueError("Downloaded plugin archive is not a valid ZIP file") from exc
        with package:
            infos = package.infolist()
            if not infos or len(infos) > MAX_ARCHIVE_FILES:
                raise ValueError("Plugin archive has an invalid number of files")
            seen_paths: set[str] = set()
            total_size = 0
            for info in infos:
                name = info.filename
                try:
                    path = self._validate_relative_path(name)
                except ValueError as exc:
                    raise ValueError(
                        f"Plugin archive contains an invalid path or path traversal: {name}"
                    ) from exc
                normalized = "/".join(path.parts).casefold()
                if normalized in seen_paths:
                    raise ValueError("Plugin archive contains duplicate paths")
                seen_paths.add(normalized)
                lowered_parts = tuple(part.casefold() for part in path.parts)
                if (
                    any(part in {"cache", "__pycache__", ".git"} for part in lowered_parts)
                    or path.name.casefold().endswith(".log")
                    or "settings" in path.name.casefold()
                    and path.name.casefold().endswith(".json")
                ):
                    raise ValueError("Plugin archive contains private or generated data")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.external_attr & 0x400:
                    raise ValueError("Plugin archive must not contain symbolic links")
                total_size += info.file_size
                if total_size > MAX_EXTRACTED_BYTES:
                    raise ValueError("Plugin archive expands beyond the permitted size")
                if info.file_size and info.compress_size == 0:
                    raise ValueError("Plugin archive contains an invalid compressed file")
                if info.compress_size and info.file_size / info.compress_size > 200:
                    raise ValueError("Plugin archive compression ratio is too high")
                target = destination.joinpath(*path.parts)
                resolved = target.resolve()
                root = destination.resolve()
                if resolved != root and root not in resolved.parents:
                    raise ValueError("Plugin archive path escapes its install directory")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with package.open(info) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                except (EOFError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
                    raise ValueError("Plugin archive contains invalid compressed data") from exc

        manifest_path = destination / "manifest.json"
        manifest = self._read_manifest(manifest_path)
        if manifest.get("id") != entry.plugin_id:
            raise ValueError("Plugin archive manifest ID does not match the catalog")
        if manifest.get("version") != entry.version:
            raise ValueError("Plugin archive manifest version does not match the catalog")
        if manifest.get("min_keydeck_version") != entry.min_keydeck_version:
            raise ValueError("Plugin archive compatibility does not match the catalog")
        if manifest.get("max_keydeck_version") != entry.max_keydeck_version:
            raise ValueError("Plugin archive compatibility does not match the catalog")
        if tuple(manifest.get("permissions", [])) != entry.permissions:
            raise ValueError("Plugin archive permissions do not match the catalog")
        if tuple(manifest.get("action_prefixes", [])) != entry.action_prefixes:
            raise ValueError("Plugin archive action prefixes do not match the catalog")
        if version_key(entry.min_keydeck_version) > version_key(self.keydeck_version):
            raise ValueError(f"{entry.name} requires a newer KeyDeck version")
        if entry.max_keydeck_version is not None and version_key(
            self.keydeck_version
        ) > version_key(entry.max_keydeck_version):
            raise ValueError(f"{entry.name} does not support this KeyDeck version")
        self._validate_relative_file(destination, manifest.get("entry", "plugin.py"))
        settings_file = manifest.get("settings") or manifest.get("settings_file")
        if settings_file is not None:
            self._validate_relative_path(settings_file)

    def _validate_entry(self, entry: PluginCatalogEntry) -> None:
        if not isinstance(entry, PluginCatalogEntry):
            raise TypeError("Plugin install requires a catalog entry")
        self._validate_plugin_id(entry.plugin_id)
        if not isinstance(entry.name, str) or not entry.name.strip():
            raise ValueError("Plugin catalog entry has no name")
        if not isinstance(entry.description, str) or not entry.description.strip():
            raise ValueError("Plugin catalog entry has no description")
        if not isinstance(entry.permissions, tuple) or any(
            not isinstance(permission, str) or permission not in ALLOWED_PERMISSIONS
            for permission in entry.permissions
        ):
            raise ValueError("Plugin catalog entry declares invalid permissions")
        if len(set(entry.permissions)) != len(entry.permissions):
            raise ValueError("Plugin catalog entry repeats a permission")
        if not isinstance(entry.action_prefixes, tuple) or any(
            not isinstance(prefix, str) or not _PLUGIN_ID_PATTERN.fullmatch(prefix)
            for prefix in entry.action_prefixes
        ):
            raise ValueError("Plugin catalog entry has invalid action prefixes")
        version_key(entry.version)
        version_key(entry.min_keydeck_version)
        if version_key(entry.min_keydeck_version) > version_key(self.keydeck_version):
            raise ValueError(f"{entry.name} requires a newer KeyDeck version")
        if entry.max_keydeck_version is not None:
            version_key(entry.max_keydeck_version)
            if version_key(entry.max_keydeck_version) < version_key(
                entry.min_keydeck_version
            ):
                raise ValueError("Plugin catalog entry has an invalid compatibility range")
            if version_key(self.keydeck_version) > version_key(entry.max_keydeck_version):
                raise ValueError(f"{entry.name} does not support this KeyDeck version")

    def _plugin_path(self, plugin_id: str) -> Path:
        self._validate_plugin_id(plugin_id)
        root = self.installed_plugins_dir.resolve()
        candidate = (root / plugin_id).resolve()
        if candidate.parent != root:
            raise ValueError("Plugin path must remain inside the install directory")
        return candidate

    @staticmethod
    def _validate_plugin_id(plugin_id: str) -> None:
        if not isinstance(plugin_id, str) or not _PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise ValueError("Invalid plugin ID")

    @staticmethod
    def _validate_relative_path(value: Any) -> PurePosixPath:
        if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
            raise ValueError("Plugin manifest contains an invalid relative path")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(":" in part or part.endswith((" ", ".")) for part in path.parts)
            or any(
                part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
                for part in path.parts
            )
        ):
            raise ValueError("Plugin manifest path escapes its package")
        return path

    @classmethod
    def _validate_relative_file(cls, root: Path, value: Any) -> Path:
        relative = cls._validate_relative_path(value)
        candidate = root.joinpath(*relative.parts)
        resolved_root = root.resolve()
        resolved = candidate.resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ValueError("Plugin manifest path escapes its package")
        if not candidate.is_file():
            raise ValueError(f"Plugin entry file is missing: {value}")
        return candidate

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Plugin package has an invalid manifest") from exc
        if not isinstance(manifest, dict):
            raise ValueError("Plugin package manifest must be a JSON object")
        return manifest

    @staticmethod
    def _remove_directory(path: Path) -> None:
        if path.is_symlink():
            raise ValueError("Refusing to remove a symbolic link from plugin storage")
        if path.is_dir():
            shutil.rmtree(path)
