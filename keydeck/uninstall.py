from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from keydeck.config import APP_DATA_DIR
from keydeck.updates import schedule_helper_cleanup, wait_for_process_exit


_WINDOWS_CLEANUP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = [System.IO.Path]::GetFullPath($env:KEYDECK_UNINSTALL_TARGET)
$task = Get-ScheduledTask -TaskName 'KeyDeck_AutoStart' -ErrorAction SilentlyContinue
if ($null -ne $task) {
    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $currentUserNames = @($currentUser, $env:USERNAME)
    if ($env:USERDOMAIN) {
        $currentUserNames += "$env:USERDOMAIN\$env:USERNAME"
    }
    $currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    foreach ($candidate in @($task)) {
        $principal = $candidate.Principal.UserId
        $ownsTask = $currentUserNames -contains $principal -or $principal -eq $currentUserSid
        if (-not $ownsTask -and $principal) {
            try {
                $account = [System.Security.Principal.NTAccount]::new($principal)
                $principalSid = $account.Translate([System.Security.Principal.SecurityIdentifier]).Value
                $ownsTask = $principalSid -eq $currentUserSid
            } catch {
                $ownsTask = $false
            }
        }
        foreach ($action in $candidate.Actions) {
            if (-not $action.Execute -or
                -not [System.String]::Equals(
                    [System.IO.Path]::GetFullPath($action.Execute),
                    $target,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                $ownsTask = $false
            }
        }
        if ($ownsTask) {
            Unregister-ScheduledTask -InputObject $candidate -Confirm:$false -ErrorAction Stop
        }
    }
}
$shell = New-Object -ComObject WScript.Shell
$folders = @(
    [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::DesktopDirectory),
    [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Programs)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }
foreach ($folder in $folders) {
    Get-ChildItem -LiteralPath $folder -Filter 'KeyDeck*.lnk' -File | ForEach-Object {
        $shortcut = $shell.CreateShortcut($_.FullName)
        if ($shortcut.TargetPath -and
            [System.String]::Equals(
                [System.IO.Path]::GetFullPath($shortcut.TargetPath),
                $target,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            Remove-Item -LiteralPath $_.FullName -Force
        }
    }
}
"""


def launch_uninstaller(
    executable_path: Path,
    pid: int,
    *,
    preserve_user_data: bool,
) -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("Uninstall is available only in the Windows release build")
    executable_path = executable_path.resolve()
    if not executable_path.is_file():
        raise FileNotFoundError(f"KeyDeck executable was not found: {executable_path}")

    descriptor, helper_name = tempfile.mkstemp(
        prefix="KeyDeckUninstaller-",
        suffix=".exe",
    )
    os.close(descriptor)
    helper_path = Path(helper_name)
    try:
        shutil.copy2(executable_path, helper_path)
        subprocess.Popen(
            [
                str(helper_path),
                "--uninstall",
                str(executable_path),
                str(pid),
                "1" if preserve_user_data else "0",
            ],
            cwd=str(helper_path.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        helper_path.unlink(missing_ok=True)
        raise


def run_uninstaller(arguments: list[str]) -> int:
    helper_path = Path(sys.argv[0]).resolve()
    valid_helper = (
        helper_path.parent == Path(tempfile.gettempdir()).resolve()
        and re.fullmatch(r"KeyDeckUninstaller-[^.]+\.exe", helper_path.name) is not None
    )
    try:
        if not valid_helper:
            raise ValueError("The uninstaller must run from its temporary helper executable")
        if len(arguments) != 3:
            raise ValueError("The uninstaller received invalid arguments")
        executable_path = Path(arguments[0]).resolve(strict=True)
        pid = int(arguments[1])
        preserve_user_data = arguments[2]
        if pid <= 0 or preserve_user_data not in {"0", "1"}:
            raise ValueError("The uninstaller received invalid arguments")
        if executable_path == helper_path or not executable_path.is_file():
            raise ValueError("The KeyDeck executable path is invalid")

        wait_for_process_exit(pid)
        if preserve_user_data == "0":
            _validated_user_data_dir()
        _remove_startup_task_and_shortcuts(executable_path)
        executable_path.unlink()
        if preserve_user_data == "0":
            _remove_user_data()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        _show_uninstall_message(
            f"KeyDeck could not be completely removed.\n\n{exc}",
            error=True,
        )
        return 1
    finally:
        if valid_helper:
            try:
                helper_path.unlink(missing_ok=True)
            except OSError:
                schedule_helper_cleanup(helper_path)

    data_status = (
        "Your settings, plugin data, installed plugins, and backups were kept."
        if preserve_user_data == "1"
        else "KeyDeck settings and plugin data were removed."
    )
    _show_uninstall_message(
        f"KeyDeck was removed.\n\n{data_status}",
        error=False,
    )
    return 0


def _remove_startup_task_and_shortcuts(executable_path: Path) -> None:
    environment = os.environ.copy()
    environment["KEYDECK_UNINSTALL_TARGET"] = str(executable_path)
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _WINDOWS_CLEANUP_SCRIPT,
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=environment,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        message = "Could not remove the Windows startup task or KeyDeck shortcuts"
        if details:
            message = f"{message}: {details}"
        raise OSError(message)


def _remove_user_data() -> None:
    data_dir = _validated_user_data_dir()
    if data_dir is not None:
        shutil.rmtree(data_dir)


def _validated_user_data_dir() -> Path | None:
    data_dir = APP_DATA_DIR
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA")
        or Path.home() / "AppData" / "Local"
    ).resolve()
    expected_data_dir = local_app_data / "KeyDeck"
    if data_dir.resolve() != expected_data_dir or data_dir.name.casefold() != "keydeck":
        raise ValueError("Refusing to remove data outside the KeyDeck user-data folder")

    try:
        data_dir.lstat()
    except FileNotFoundError:
        return None
    _validate_removable_tree(data_dir)
    return data_dir


def _validate_removable_tree(root: Path) -> None:
    pending = [root]
    while pending:
        current = pending.pop()
        if _is_reparse_point(current):
            raise ValueError(f"Refusing to remove a reparse point: {current}")
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_symlink() or _is_reparse_point(path):
                    raise ValueError(f"Refusing to remove a linked path: {path}")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _show_uninstall_message(message: str, *, error: bool) -> None:
    if sys.platform != "win32":
        return
    icon = 0x10 if error else 0x40
    title = "KeyDeck uninstall failed" if error else "KeyDeck uninstalled"
    ctypes.windll.user32.MessageBoxW(None, message, title, icon)
