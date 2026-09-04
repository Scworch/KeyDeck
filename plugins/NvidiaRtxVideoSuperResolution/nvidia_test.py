"""Interactive diagnostic for NVIDIA RTX Video Super Resolution registry changes.

The script never changes the registry. For every requested mode it waits until
the user changes the setting in NVIDIA's UI and confirms with Enter, then
records the complete NVIDIA registry snapshot and the values that changed.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import winreg


GPU_CLASS = (
    r"SYSTEM\CurrentControlSet\Control\Class"
    r"\{4d36e968-e325-11ce-bfc1-08002be10318}"
)
TARGET_VALUE = "_User_Global_VAL_SuperResolution"
MODES = ("off", "1", "2", "3", "4", "auto")
MODE_LABELS = {
    "off": "OFF",
    "1": "Quality 1",
    "2": "Quality 2",
    "3": "Quality 3",
    "4": "Quality 4",
    "auto": "AUTO",
}
SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_PATH = SCRIPT_DIR / "nvidia_test_results.json"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def run_as_admin() -> bool:
    script = str(Path(__file__).resolve())
    params = subprocess.list2cmdline([script, *sys.argv[1:]])
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        str(SCRIPT_DIR),
        1,
    )
    if result <= 32:
        print(f"Не удалось запросить права администратора (код {result}).")
        return False
    return True


def serialize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    if isinstance(value, tuple):
        return [serialize_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def find_nvidia_keys() -> list[dict[str, str]]:
    keys: list[dict[str, str]] = []
    for index in range(100):
        relative_path = f"{GPU_CLASS}\\{index:04d}"
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                relative_path,
                0,
                winreg.KEY_READ,
            ) as key:
                try:
                    provider, _ = winreg.QueryValueEx(key, "ProviderName")
                except FileNotFoundError:
                    continue
                if "nvidia" in str(provider).casefold():
                    keys.append(
                        {
                            "path": relative_path,
                            "provider": str(provider),
                        }
                    )
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            print(f"Нет доступа к HKLM\\{relative_path}: {exc}")
    return keys


def read_key_snapshot(key_info: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        key_info["path"],
        0,
        winreg.KEY_READ,
    ) as key:
        value_count = winreg.QueryInfoKey(key)[1]
        for index in range(value_count):
            try:
                name, value, value_type = winreg.EnumValue(key, index)
            except OSError:
                continue
            values[name] = {
                "value": serialize_value(value),
                "type": value_type,
            }
    return {
        "provider": key_info["provider"],
        "path": key_info["path"],
        "values": values,
    }


def snapshot(keys: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key_info in keys:
        try:
            item = read_key_snapshot(key_info)
        except (FileNotFoundError, OSError) as exc:
            item = {
                "provider": key_info["provider"],
                "path": key_info["path"],
                "error": f"{type(exc).__name__}: {exc}",
                "values": {},
            }
        result[key_info["path"]] = item
    return result


def changed_values(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        before_values = before.get(path, {}).get("values", {})
        after_values = after.get(path, {}).get("values", {})
        for name in sorted(set(before_values) | set(after_values)):
            old = before_values.get(name)
            new = after_values.get(name)
            if old != new:
                changes.append(
                    {
                        "path": path,
                        "name": name,
                        "before": old,
                        "after": new,
                    }
                )
    return changes


def target_value(snapshot_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path, key_data in snapshot_data.items():
        value_data = key_data.get("values", {}).get(TARGET_VALUE)
        if value_data is not None:
            result[path] = value_data
    return result


def write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    if os.name != "nt":
        raise RuntimeError("Этот диагностический скрипт предназначен только для Windows.")

    if not is_admin():
        print("Для полного чтения NVIDIA-разделов нужны права администратора.")
        print("Запрашиваю повышение прав через UAC...")
        if run_as_admin():
            return
        raise RuntimeError("Скрипт не был запущен от администратора.")

    print("=" * 78)
    print(" NVIDIA RTX VIDEO SUPER RESOLUTION - INTERACTIVE TEST")
    print("=" * 78)
    print(f"Отчёт будет сохранён в:\n{REPORT_PATH}")
    print()

    keys = find_nvidia_keys()
    if not keys:
        raise RuntimeError("NVIDIA-разделы в реестре не найдены.")

    print("Найдены разделы:")
    for key_info in keys:
        print(f"  HKLM\\{key_info['path']} ({key_info['provider']})")
    print()
    print("Скрипт ничего не меняет. Изменяйте режим вручную в NVIDIA UI.")
    print("После установки указанного режима нажмите Enter.")

    report: dict[str, Any] = {
        "started_at": datetime.now().astimezone().isoformat(),
        "registry_root": f"HKLM\\{GPU_CLASS}",
        "target_value": TARGET_VALUE,
        "modes": {},
    }
    previous_snapshot = snapshot(keys)

    for number, mode in enumerate(MODES, 1):
        print()
        print("-" * 78)
        print(f"[{number}/{len(MODES)}] Установите RTX Video Super Resolution = {MODE_LABELS[mode]}")
        input("Когда режим установлен, нажмите Enter для чтения реестра...")
        current_snapshot = snapshot(keys)
        changes = changed_values(previous_snapshot, current_snapshot)
        report["modes"][mode] = {
            "label": MODE_LABELS[mode],
            "captured_at": datetime.now().astimezone().isoformat(),
            "target_values": target_value(current_snapshot),
            "changed_values_since_previous_mode": changes,
            "registry_snapshot": current_snapshot,
        }
        write_report(report)
        print(f"Снимок сохранён. Изменений значений: {len(changes)}")
        for change in changes:
            print(
                f"  {change['path']}\\{change['name']}: "
                f"{change['before']} -> {change['after']}"
            )
        previous_snapshot = current_snapshot

    report["finished_at"] = datetime.now().astimezone().isoformat()
    write_report(report)
    print()
    print("=" * 78)
    print("ТЕСТ ЗАВЕРШЁН")
    print(f"Полный отчёт: {REPORT_PATH}")
    print("=" * 78)
    input("Нажмите Enter для выхода...")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, PermissionError) as exc:
        print(f"\nОШИБКА: {exc}")
        input("Нажмите Enter для выхода...")
