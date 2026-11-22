from __future__ import annotations

import ctypes
import glob
import os
import subprocess
from pathlib import Path
from typing import Any, Callable


class NetworkManager:
    def __init__(
        self,
        plugin_dir: Path,
        logger: Callable[[bool, str], None],
        data_plugins_dir: Path | None = None,
    ) -> None:
        self.plugin_dir = plugin_dir
        self.logger = logger
        self.data_plugins_dir = data_plugins_dir or plugin_dir.parent

    def start(self, mode: str, config: dict[str, Any], server: str = "") -> bool:
        if mode == "off":
            return True
        if mode == "zapret":
            return self._zapret(config.get("zapret", {}))
        if mode == "vpn":
            return self._vpn(config.get("nekobox", {}), server)
        self.logger(False, f"Сеть: неизвестный режим {mode}")
        return False

    def _zapret(self, config: dict[str, Any]) -> bool:
        configured = str(config.get("bat", "")).strip()
        bat = Path(configured) if configured else self._find_zapret_bat()
        if not bat.exists():
            self.logger(False, "Zapret: BAT-файл не найден, укажите его в настройках")
            return False
        args = str(config.get("arguments", "")).strip()
        command = f'"{bat}" {args}'.strip()
        try:
            if bool(config.get("elevated", True)) and os.name == "nt":
                result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(bat), args, str(bat.parent), 1)
                if result <= 32:
                    raise OSError(f"UAC code {result}")
            else:
                subprocess.Popen(["cmd.exe", "/c", command], cwd=str(bat.parent))
            self.logger(True, "Zapret: BAT-файл запущен")
            return True
        except (OSError, ValueError) as exc:
            self.logger(False, f"Zapret: {exc}")
            return False

    def _find_zapret_bat(self) -> Path:
        settings = self.data_plugins_dir / "ZapretToggler" / "settings.json"
        selected = ""
        try:
            import json
            data = json.loads(settings.read_text(encoding="utf-8"))
            selected = str(data.get("selected_bat", "")).strip()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        candidates = sorted(glob.glob(r"C:\zapret-discord-youtube-*"), key=os.path.getmtime, reverse=True)
        if not selected or not candidates:
            return Path()
        candidate = Path(candidates[0]) / selected
        return candidate if candidate.is_file() else Path()

    def _vpn(self, config: dict[str, Any], server: str) -> bool:
        executable = Path(str(config.get("executable", "")).strip())
        if not executable.exists():
            self.logger(False, "NekoBox: executable не найден")
            return False
        try:
            subprocess.Popen([str(executable)])
        except OSError as exc:
            self.logger(False, f"NekoBox: не удалось запустить: {exc}")
            return False
        command = str(config.get("tun_command", "")).strip()
        if not command:
            self.logger(False, f"NekoBox запущен, но TUN не подтверждён для сервера «{server or 'не выбран'}»")
            return False
        try:
            command = command.replace("{server}", server)
            result = subprocess.run(["cmd.exe", "/c", command], check=False, capture_output=True, text=True, timeout=15)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or f"код {result.returncode}")
            status_command = str(config.get("status_command", "")).strip()
            if status_command:
                status = subprocess.run(["cmd.exe", "/c", status_command], check=False, timeout=10)
                if status.returncode:
                    raise RuntimeError("проверка TUN вернула ошибку")
            self.logger(True, f"NekoBox: TUN включён для «{server or 'текущий сервер'}»")
            return True
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.logger(False, f"NekoBox: TUN не подтверждён: {exc}")
            return False
