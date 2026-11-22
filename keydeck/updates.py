from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
from urllib.parse import urlparse
import urllib.request

from keydeck import __version__

API_URL = "https://api.github.com/repos/Scworch/KeyDeck/releases/latest"
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
REQUEST_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 5
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def update_check_due(last_check: float, now: float | None = None) -> bool:
    current_time = time.time() if now is None else now
    return last_check <= 0 or current_time - last_check >= UPDATE_CHECK_INTERVAL_SECONDS


class UpdateCancelled(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    page_url: str
    executable_url: str
    checksum_url: str

    @property
    def executable_name(self) -> str:
        return f"KeyDeck-{self.tag}.exe"


def _version_key(version: str) -> tuple[int, ...]:
    normalized = version.removeprefix("v")
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", normalized):
        raise ValueError(f"Unsupported version format: {version}")
    return tuple(int(part) for part in normalized.split("."))


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    return _version_key(candidate) > _version_key(current)


def _is_github_url(url: str, path_prefix: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.username is None
        and parsed.port is None
        and parsed.path.startswith(path_prefix)
    )


def _open_url(url: str, timeout: int = REQUEST_TIMEOUT):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "KeyDeck-Updater",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def check_latest_release(cancel_event: threading.Event | None = None) -> Release | None:
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelled
    try:
        with _open_url(API_URL, timeout=DOWNLOAD_TIMEOUT) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise

    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    page_url = data.get("html_url")
    assets = data.get("assets")
    if not isinstance(tag, str) or not isinstance(page_url, str) or not isinstance(assets, list):
        raise ValueError("GitHub release metadata is incomplete")

    version = tag.removeprefix("v")
    if not is_newer_version(version):
        return None

    asset_urls: dict[str, str] = {}
    for asset in assets:
        if isinstance(asset, dict):
            name = asset.get("name")
            url = asset.get("browser_download_url")
            if isinstance(name, str) and isinstance(url, str):
                asset_urls[name] = url

    executable_url = asset_urls.get(f"KeyDeck-{tag}.exe")
    checksum_url = asset_urls.get("SHA256SUMS.txt")
    if executable_url is None or checksum_url is None:
        raise ValueError("The latest release does not contain its executable and checksum")
    if not _is_github_url(page_url, "/Scworch/KeyDeck/releases/tag/"):
        raise ValueError("The latest release page is not from the official KeyDeck repository")
    for asset_url in (executable_url, checksum_url):
        if not _is_github_url(asset_url, "/Scworch/KeyDeck/releases/download/"):
            raise ValueError("A release download URL is not from the official KeyDeck repository")

    return Release(version, tag, page_url, executable_url, checksum_url)


def _read_limited(
    response,
    limit: int,
    cancel_event: threading.Event | None = None,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise UpdateCancelled
        chunk = response.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise ValueError("The update download exceeds the permitted size")
        chunks.append(chunk)


def download_release(
    release: Release,
    cancel_event: threading.Event | None = None,
) -> tuple[Path, Path]:
    if not _is_github_url(
        release.executable_url,
        "/Scworch/KeyDeck/releases/download/",
    ) or not _is_github_url(
        release.checksum_url,
        "/Scworch/KeyDeck/releases/download/",
    ):
        raise ValueError("Release downloads must come from the official KeyDeck repository")
    download_dir = Path(tempfile.mkdtemp(prefix="KeyDeck-update-"))
    executable_path = download_dir / release.executable_name
    try:
        with _open_url(release.checksum_url, timeout=DOWNLOAD_TIMEOUT) as response:
            checksums = _read_limited(response, 64 * 1024, cancel_event).decode("utf-8")
        expected_digest = None
        for line in checksums.splitlines():
            match = re.fullmatch(
                rf"([0-9a-fA-F]{{64}})\s+\*?{re.escape(executable_path.name)}",
                line.strip(),
            )
            if match:
                expected_digest = match.group(1).lower()
                break
        if expected_digest is None:
            raise ValueError("The release checksum does not list the executable")

        with _open_url(release.executable_url, timeout=DOWNLOAD_TIMEOUT) as response:
            executable = _read_limited(response, MAX_DOWNLOAD_BYTES, cancel_event)
        if not executable.startswith(b"MZ"):
            raise ValueError("The downloaded update is not a Windows executable")
        if hashlib.sha256(executable).hexdigest() != expected_digest:
            raise ValueError("The downloaded update failed its SHA-256 check")
        executable_path.write_bytes(executable)
        return executable_path, download_dir
    except (
        UpdateCancelled,
        http.client.HTTPException,
        OSError,
        UnicodeDecodeError,
        ValueError,
    ):
        shutil.rmtree(download_dir, ignore_errors=True)
        raise


def wait_for_process_exit(pid: int, timeout_ms: int = 120_000) -> None:
    synchronize = 0x00100000
    wait_object_0 = 0
    wait_timeout = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process = kernel32.OpenProcess(synchronize, False, pid)
    if not process:
        error = ctypes.get_last_error()
        if error == 87:
            return
        raise OSError(error, "Could not open KeyDeck to wait for it to exit")
    try:
        result = kernel32.WaitForSingleObject(process, timeout_ms)
        if result == wait_timeout:
            raise TimeoutError("KeyDeck did not close in time to install the update")
        if result != wait_object_0:
            raise OSError(ctypes.get_last_error(), "Could not wait for KeyDeck to exit")
    finally:
        kernel32.CloseHandle(process)


def apply_update(executable_path: Path, target_path: Path, pid: int) -> None:
    wait_for_process_exit(pid)
    executable_path = executable_path.resolve()
    target_path = target_path.resolve()
    if executable_path == target_path or not executable_path.is_file():
        raise ValueError("The staged update executable is missing or invalid")
    with executable_path.open("rb") as executable:
        if executable.read(2) != b"MZ":
            raise ValueError("The staged update is not a Windows executable")

    temporary_path = target_path.with_name(f".{target_path.name}.new")
    backup_path = target_path.with_name(f".{target_path.name}.backup-{pid}")
    old_moved = False
    try:
        shutil.copy2(executable_path, temporary_path)
        os.replace(target_path, backup_path)
        old_moved = True
        os.replace(temporary_path, target_path)
        notify_shell_icon_changed(target_path)
        subprocess.Popen([str(target_path)], cwd=str(target_path.parent))
    except OSError as update_error:
        if old_moved:
            target_path.unlink(missing_ok=True)
            os.replace(backup_path, target_path)
        try:
            subprocess.Popen([str(target_path)], cwd=str(target_path.parent))
        except OSError as restart_error:
            raise RuntimeError(
                f"Update failed and the previous KeyDeck could not be restarted: {restart_error}"
            ) from update_error
        raise
    else:
        try:
            backup_path.unlink()
        except OSError:
            schedule_helper_cleanup(backup_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def notify_shell_icon_changed(executable_path: Path) -> None:
    if sys.platform != "win32":
        return
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHChangeNotify.argtypes = [
        ctypes.c_long,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
    ]
    shell32.SHChangeNotify.restype = None
    shell32.SHChangeNotify(0x00002000, 0x0005, str(executable_path), None)


def _show_update_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "KeyDeck update failed", 0x10)


def run_updater(arguments: list[str]) -> int:
    if len(arguments) != 3:
        _show_update_error("The updater received invalid arguments.")
        return 2
    helper_path = Path(sys.argv[0]).resolve()
    if helper_path.parent != Path(tempfile.gettempdir()).resolve() or not re.fullmatch(
        r"KeyDeckUpdater-[^.]+\.exe",
        helper_path.name,
    ):
        _show_update_error("The updater must run from its temporary helper executable.")
        return 2
    executable_path, target_path, pid_text = arguments
    try:
        apply_update(Path(executable_path), Path(target_path), int(pid_text))
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        _show_update_error(f"KeyDeck could not be updated. Your existing settings were not changed.\n\n{exc}")
        return 1
    finally:
        staged_path = Path(executable_path).resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        if (
            staged_path.parent.parent == temporary_root
            and staged_path.parent.name.startswith("KeyDeck-update-")
            and re.fullmatch(r"KeyDeck-v?\d+(?:\.\d+){1,3}\.exe", staged_path.name)
        ):
            try:
                staged_path.unlink(missing_ok=True)
            except OSError:
                schedule_helper_cleanup(staged_path)
            try:
                staged_path.parent.rmdir()
            except OSError:
                pass
        schedule_helper_cleanup(helper_path)
    return 0


def launch_update_helper(executable_path: Path, download_dir: Path, target_path: Path, pid: int) -> None:
    descriptor, helper_name = tempfile.mkstemp(
        prefix="KeyDeckUpdater-",
        suffix=".exe",
    )
    os.close(descriptor)
    helper_path = Path(helper_name)
    try:
        shutil.copy2(executable_path, helper_path)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                str(helper_path),
                "--apply-update",
                str(executable_path),
                str(target_path),
                str(pid),
            ],
            cwd=str(download_dir),
            creationflags=flags,
        )
    except OSError:
        helper_path.unlink(missing_ok=True)
        shutil.rmtree(download_dir, ignore_errors=True)
        raise


def schedule_helper_cleanup(helper_path: Path) -> None:
    movefile_delay_until_reboot = 0x00000004
    ctypes.windll.kernel32.MoveFileExW(
        str(helper_path),
        None,
        movefile_delay_until_reboot,
    )
