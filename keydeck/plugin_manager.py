from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

from keydeck.plugin_api import Action, PluginBase, PluginContext


class PluginManager:
    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = plugins_dir
        self.plugins: list[PluginBase] = []
        self.script_actions: list[Action] = []
        self.errors: list[str] = []

    def load_plugins(self) -> None:
        self.plugins = []
        self.script_actions = []
        self.errors = []

        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue

            try:
                context = self._build_context(plugin_dir)
                plugin = self._load_plugin_instance(context)
                if plugin is not None:
                    self.plugins.append(plugin)
                    continue

                self.script_actions.append(self._build_script_action(context))
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{plugin_dir.name}: {exc}")

    def all_actions(self) -> list[Action]:
        actions: list[Action] = []
        for plugin in self.plugins:
            try:
                plugin_actions = plugin.actions()
                for action in plugin_actions:
                    if not action.plugin_id:
                        action.plugin_id = (
                            plugin.context.plugin_id if plugin.context else plugin.__class__.__name__
                        )
                    if action.settings_callback is None:
                        action.settings_callback = plugin.open_settings
                actions.extend(plugin_actions)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(
                    f"{getattr(plugin, 'plugin_name', plugin.__class__.__name__)}: {exc}"
                )
        actions.extend(self.script_actions)
        return actions

    def _build_context(self, plugin_dir: Path) -> PluginContext:
        manifest_path = plugin_dir / "manifest.json"
        manifest = self._load_manifest(manifest_path)

        entry_name = str(manifest.get("entry", "plugin.py")).strip() or "plugin.py"
        entry_file = (plugin_dir / entry_name).resolve()
        if not entry_file.exists():
            raise FileNotFoundError(f"Entry file not found: {entry_name}")

        plugin_id = str(manifest.get("id", plugin_dir.name))
        plugin_name = str(manifest.get("name", plugin_dir.name))
        settings_file = self._resolve_settings_file(plugin_dir, manifest)

        if not settings_file.exists():
            settings_file.write_text("{}\n", encoding="utf-8")

        return PluginContext(
            plugin_id=plugin_id,
            plugin_name=plugin_name,
            plugin_dir=plugin_dir.resolve(),
            entry_file=entry_file,
            settings_file=settings_file.resolve(),
            manifest=manifest,
        )

    def _load_manifest(self, manifest_path: Path) -> dict:
        if not manifest_path.exists():
            return {}
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("manifest.json must contain a JSON object")
        return raw

    def _resolve_settings_file(self, plugin_dir: Path, manifest: dict) -> Path:
        configured = manifest.get("settings") or manifest.get("settings_file")
        if isinstance(configured, str) and configured.strip():
            return (plugin_dir / configured.strip()).resolve()

        matches = sorted(plugin_dir.glob("*settings*.json"))
        if len(matches) == 1:
            return matches[0].resolve()
        return (plugin_dir / "settings.json").resolve()

    def _load_plugin_instance(self, context: PluginContext) -> PluginBase | None:
        module_name = f"keydeck_plugin_{context.plugin_id}"
        spec = importlib.util.spec_from_file_location(module_name, context.entry_file)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot create import spec")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        plugin_class = getattr(module, "Plugin", None)
        if plugin_class is None:
            return None

        plugin = self._construct_plugin(plugin_class, context)
        if not isinstance(plugin, PluginBase):
            raise TypeError("Plugin class must inherit PluginBase")
        return plugin

    def _construct_plugin(self, plugin_class: type, context: PluginContext) -> PluginBase:
        try:
            return plugin_class(context=context)
        except TypeError:
            pass

        try:
            params = list(inspect.signature(plugin_class).parameters.values())
            if params and params[0].name == "context":
                return plugin_class(context)
        except (TypeError, ValueError):
            pass

        plugin = plugin_class()
        if getattr(plugin, "context", None) is None:
            plugin.context = context
        return plugin

    def _build_script_action(self, context: PluginContext) -> Action:
        return Action(
            action_id=f"{context.plugin_id}.run",
            title=context.plugin_name,
            callback=lambda: self._run_script_plugin(context),
            plugin_id=context.plugin_id,
            settings_callback=lambda: self._open_settings_file(context),
        )

    def _run_script_plugin(self, context: PluginContext) -> None:
        args = self._script_args(context)
        result = subprocess.run(
            [sys.executable, str(context.entry_file), *args],
            cwd=str(context.plugin_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            details = stderr or stdout or f"Exit code {result.returncode}"
            raise RuntimeError(f"[{context.plugin_name}] {details}")

    def _script_args(self, context: PluginContext) -> list[str]:
        raw_args = context.manifest.get("args")
        if not isinstance(raw_args, list):
            return []

        args: list[str] = []
        for item in raw_args:
            if not isinstance(item, str):
                continue
            arg = item.replace("{settings_file}", str(context.settings_file))
            arg = arg.replace("{plugin_dir}", str(context.plugin_dir))
            args.append(arg)
        return args

    def _open_settings_file(self, context: PluginContext) -> None:
        os.startfile(str(context.settings_file))
