#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import winreg


STEAM_REG_PATH = r"Software\Valve\Steam"
MAX_KILL_RETRIES = 10
DEFAULT_CONFIG_NAME = "steam_switch_settings.json"


def read_registry_string(root: Any, key_path: str, value_name: str) -> str:
    with winreg.OpenKey(root, key_path) as key:
        value, value_type = winreg.QueryValueEx(key, value_name)
        if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            raise RuntimeError(f"Registry value {value_name} has unexpected type: {value_type}")
        return str(value)


def write_registry_string(root: Any, key_path: str, value_name: str, value: str) -> None:
    with winreg.OpenKey(root, key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)


def tokenize_vdf(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch in "{}":
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            else:
                raise ValueError("Unclosed quote in VDF")
            tokens.append("".join(buf))
            continue
        raise ValueError(f"Unexpected VDF character: {ch!r} at position {i}")
    return tokens


def parse_vdf(text: str) -> dict[str, Any]:
    tokens = tokenize_vdf(text)
    idx = 0

    def parse_object(stop_on_brace: bool = False) -> dict[str, Any]:
        nonlocal idx
        obj: dict[str, Any] = {}
        while idx < len(tokens):
            tok = tokens[idx]
            if tok == "}":
                if stop_on_brace:
                    idx += 1
                    return obj
                raise ValueError("Unexpected closing brace")
            key = tok
            idx += 1
            if idx >= len(tokens):
                raise ValueError(f"Missing value for key: {key}")
            nxt = tokens[idx]
            if nxt == "{":
                idx += 1
                obj[key] = parse_object(stop_on_brace=True)
            else:
                obj[key] = nxt
                idx += 1
        if stop_on_brace:
            raise ValueError("Missing closing brace")
        return obj

    parsed = parse_object(stop_on_brace=False)
    if idx != len(tokens):
        raise ValueError("Unexpected extra tokens at end")
    return parsed


def dump_vdf(data: dict[str, Any], indent: str = "\t") -> str:
    def render(obj: dict[str, Any], level: int) -> list[str]:
        lines: list[str] = []
        for key, value in obj.items():
            pad = indent * level
            if isinstance(value, dict):
                lines.append(f'{pad}"{key}"')
                lines.append(f"{pad}" + "{")
                lines.extend(render(value, level + 1))
                lines.append(f"{pad}" + "}")
            else:
                lines.append(f'{pad}"{key}" "{value}"')
        return lines

    return "\n".join(render(data, 0)) + "\n"


def is_steam_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq steam.exe"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout + "\n" + result.stderr).lower()
    return "steam.exe" in output


def stop_steam() -> None:
    retries = 0
    while is_steam_running():
        subprocess.run(["taskkill", "/IM", "steam.exe", "/F"], check=False, capture_output=True)
        retries += 1
        if retries > MAX_KILL_RETRIES:
            raise RuntimeError("Steam is still running after repeated kill attempts")
        time.sleep(1.0)


def start_steam() -> None:
    subprocess.run(["cmd", "/c", "start", "", "steam://open/main"], check=True)


def get_steam_path() -> Path:
    steam_path = read_registry_string(winreg.HKEY_CURRENT_USER, STEAM_REG_PATH, "SteamPath")
    return Path(steam_path)


def load_loginusers(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    data = parse_vdf(text)
    if "users" not in data or not isinstance(data["users"], dict):
        raise RuntimeError("Invalid loginusers.vdf: missing 'users' object")
    return data


def list_remembered_accounts(data: dict[str, Any]) -> list[tuple[str, str]]:
    users = data.get("users", {})
    items: list[tuple[str, str]] = []
    for steam_id, record in users.items():
        if not isinstance(record, dict):
            continue
        if str(record.get("RememberPassword", "0")) != "1":
            continue
        account_name = str(record.get("AccountName", "")).strip()
        persona_name = str(record.get("PersonaName", "")).strip()
        if account_name:
            items.append((account_name, persona_name or account_name))
    return items


def set_allow_autologin_for_all_users(data: dict[str, Any]) -> None:
    users = data.get("users", {})
    for record in users.values():
        if isinstance(record, dict):
            record["AllowAutoLogin"] = "1"


def find_user_record(data: dict[str, Any], account_name: str) -> tuple[str, dict[str, Any]] | None:
    target = account_name.strip().lower()
    users = data.get("users", {})
    for steam_id, record in users.items():
        if not isinstance(record, dict):
            continue
        acc = str(record.get("AccountName", "")).strip().lower()
        if acc == target:
            return steam_id, record
    return None


def switch_account(
    account_name: str,
    close_steam_before_switch: bool = True,
    launch_steam_after_switch: bool = True,
) -> None:
    steam_path = get_steam_path()
    loginusers_path = steam_path / "config" / "loginusers.vdf"
    if not loginusers_path.exists():
        raise RuntimeError(f"loginusers.vdf not found: {loginusers_path}")

    data = load_loginusers(loginusers_path)
    found = find_user_record(data, account_name)
    if not found:
        raise RuntimeError(f"Account not found in loginusers.vdf: {account_name}")
    _, user = found

    if str(user.get("RememberPassword", "0")) != "1":
        raise RuntimeError(
            f"Account '{account_name}' has RememberPassword!=1. Sign in once in Steam with 'Remember me'."
        )

    if close_steam_before_switch:
        stop_steam()
    set_allow_autologin_for_all_users(data)
    loginusers_path.write_text(dump_vdf(data), encoding="utf-8")
    write_registry_string(
        winreg.HKEY_CURRENT_USER,
        STEAM_REG_PATH,
        "AutoLoginUser",
        str(user.get("AccountName", account_name)),
    )
    if launch_steam_after_switch:
        start_steam()


def default_config() -> dict[str, Any]:
    return {
        "selected_account": "",
        "close_steam_before_switch": True,
        "launch_steam_after_switch": True,
    }


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        cfg = default_config()
        save_config(config_path, cfg)
        return cfg
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read config file {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Config file must contain a JSON object: {config_path}")
    cfg = default_config()
    cfg.update(raw)
    return cfg


def save_config(config_path: Path, cfg: dict[str, Any]) -> None:
    config_path.write_text(json.dumps(cfg, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def set_selected_account_in_config(config_path: Path, account_name: str) -> None:
    cfg = load_config(config_path)
    cfg["selected_account"] = account_name
    save_config(config_path, cfg)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-shot Steam account switcher for Stream Deck-like bind systems."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name(DEFAULT_CONFIG_NAME)),
        help=f"Path to config JSON file (default: ./{DEFAULT_CONFIG_NAME})",
    )
    parser.add_argument("--account", help="Steam AccountName to switch to")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List accounts available for switching (RememberPassword == 1)",
    )
    parser.add_argument(
        "--set-account",
        help="Save selected account into config file and exit",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print effective config and exit",
    )
    args = parser.parse_args()

    try:
        config_path = Path(args.config).expanduser().resolve()
        cfg = load_config(config_path)

        steam_path = get_steam_path()
        loginusers_path = steam_path / "config" / "loginusers.vdf"
        data = load_loginusers(loginusers_path)

        if args.list:
            accounts = list_remembered_accounts(data)
            if not accounts:
                print("No remembered Steam accounts found.")
                return 0
            for account, persona in accounts:
                print(f"{account}\t({persona})")
            return 0

        if args.show_config:
            print(json.dumps(cfg, ensure_ascii=True, indent=2))
            return 0

        if args.set_account:
            found = find_user_record(data, args.set_account)
            if not found:
                raise RuntimeError(f"Account not found in loginusers.vdf: {args.set_account}")
            _, user = found
            if str(user.get("RememberPassword", "0")) != "1":
                raise RuntimeError(
                    f"Account '{args.set_account}' has RememberPassword!=1. Sign in once in Steam with 'Remember me'."
                )
            set_selected_account_in_config(config_path, str(user.get("AccountName", args.set_account)))
            print(f"Config updated: selected_account={user.get('AccountName', args.set_account)}")
            return 0

        account = args.account or str(cfg.get("selected_account", "")).strip()
        if not account:
            parser.error("no account selected: use --account or set selected_account in config")

        switch_account(
            account,
            close_steam_before_switch=bool(cfg.get("close_steam_before_switch", True)),
            launch_steam_after_switch=bool(cfg.get("launch_steam_after_switch", True)),
        )

        print(f"Switched Steam auto-login to account: {account}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
