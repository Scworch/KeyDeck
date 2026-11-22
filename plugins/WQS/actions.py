from __future__ import annotations

import os
import subprocess
import time
import webbrowser
from typing import Any, Callable


class ActionEngine:
    def __init__(self, logger: Callable[[bool, str], None]) -> None:
        self.logger = logger

    def run(self, actions: list[dict[str, Any]]) -> None:
        for index, action in enumerate(actions, 1):
            if not isinstance(action, dict):
                self.logger(False, f"Действие {index}: неверный формат")
                continue
            kind = str(action.get("type", "")).lower()
            try:
                if kind in {"url", "open_url", "discord", "spotify"}:
                    url = str(action.get("url", "")).strip()
                    if not url:
                        raise ValueError("URL не указан")
                    webbrowser.open(url)
                elif kind in {"command", "script"}:
                    command = str(action.get("command", "")).strip()
                    if not command:
                        raise ValueError("Команда не указана")
                    subprocess.Popen(["cmd.exe", "/c", command], cwd=action.get("working_dir") or None)
                elif kind == "wait":
                    time.sleep(max(0, float(action.get("seconds", 1))))
                elif kind == "click":
                    raise RuntimeError("Безопасный click требует настроенного target_window и отдельного Windows input-модуля")
                else:
                    raise ValueError(f"неподдерживаемый тип: {kind or 'пусто'}")
                self.logger(True, f"Действие {index}: {kind}")
            except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
                self.logger(False, f"Действие {index}: {exc}")
