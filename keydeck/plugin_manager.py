#KeyDeck/keydeck/plugin_manager.py

from __future__ import annotations

import gc
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from keydeck.plugin_api import Action, PluginBase, PluginContext


@dataclass(frozen=True)
class PluginInfo:
    plugin_id: str
    plugin_name: str


class PluginManager:
    def __init__(
        self,
        plugins_dir: Path,
        data_dir: Path | None = None,
        legacy_data_dir: Path | None = None,
        get_assigned_slots: Callable[[], list[dict[str, Any]]] | None = None,
        invoke_assigned_slot: Callable[[str, int], None] | None = None,
    ) -> None:
        self.plugins_dir = plugins_dir
        self.data_dir = data_dir or plugins_dir
        self.legacy_data_dir = legacy_data_dir
        self.plugins: list[PluginBase] = []
        self.script_actions: list[Action] = []
        self.errors: list[str] = []
        self.disabled_plugin_ids: frozenset[str] = frozenset()
        self._plugin_module_names: set[str] = set()
        self._initial_sys_path = list(sys.path)
        self.get_assigned_slots = get_assigned_slots
        self.invoke_assigned_slot = invoke_assigned_slot

    def discover_plugins(self) -> list[PluginInfo]:
        discovered: list[PluginInfo] = []
        if not self.plugins_dir.is_dir():
            return discovered
        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            manifest_path = plugin_dir / "manifest.json"
            if not plugin_dir.is_dir() or not manifest_path.is_file():
                continue
            try:
                manifest = self._load_manifest(manifest_path)
            except (OSError, TypeError, ValueError):
                continue
            plugin_id = str(manifest.get("id", plugin_dir.name)).strip() or plugin_dir.name
            plugin_name = str(manifest.get("name", plugin_dir.name)).strip() or plugin_dir.name
            discovered.append(PluginInfo(plugin_id, plugin_name))
        return discovered

    def load_plugins(self, disabled_plugin_ids: set[str] | None = None) -> None:
        self.errors = []
        self.unload_plugins()
        self.disabled_plugin_ids = frozenset(disabled_plugin_ids or ())

        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            # The plugins directory may contain caches, user-created folders,
            # or documentation. Only a manifest identifies a loadable plugin.
            if not (plugin_dir / "manifest.json").is_file():
                continue

            try:
                manifest = self._load_manifest(plugin_dir / "manifest.json")
                plugin_id = str(manifest.get("id", plugin_dir.name)).strip() or plugin_dir.name
                if plugin_id in self.disabled_plugin_ids:
                    continue
                context = self._build_context(plugin_dir, manifest)
                plugin = self._load_plugin_instance(context)
                if plugin is not None:
                    self.plugins.append(plugin)
                    continue

                self.script_actions.append(self._build_script_action(context))
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{plugin_dir.name}: {exc}")

    def start_plugins(self) -> None:
        for plugin in self.plugins:
            try:
                plugin.start()
            except Exception as exc:  # noqa: BLE001
                self.errors.append(
                    f"Start failed for {getattr(plugin, 'plugin_name', plugin.__class__.__name__)}: {exc}"
                )

    def unload_plugins(self) -> None:
        self.stop_plugins()
        self.plugins.clear()
        self.script_actions.clear()
        self._unload_plugin_modules()

    def _unload_plugin_modules(self) -> None:
        module_names = tuple(self._plugin_module_names)
        plugin_dirs = (
            tuple(
                path.resolve()
                for path in self.plugins_dir.iterdir()
                if path.is_dir() and (path / "manifest.json").is_file()
            )
            if self.plugins_dir.is_dir()
            else ()
        )
        for name in tuple(sys.modules):
            module = sys.modules[name]
            module_path = getattr(module, "__file__", None)
            module_is_plugin_code = False
            if module_path:
                try:
                    resolved_module_path = Path(module_path).resolve()
                    module_is_plugin_code = any(
                        resolved_module_path == plugin_dir
                        or plugin_dir in resolved_module_path.parents
                        for plugin_dir in plugin_dirs
                    )
                except (OSError, RuntimeError, ValueError):
                    module_is_plugin_code = False
            if module_is_plugin_code or any(
                name == root or name.startswith(f"{root}.")
                for root in module_names
            ):
                sys.modules.pop(name, None)
        self._plugin_module_names.clear()
        plugins_root = self.plugins_dir.resolve()
        initial_paths = set(self._initial_sys_path)
        for entry in tuple(sys.path):
            if entry in initial_paths:
                continue
            try:
                resolved_entry = Path(entry or Path.cwd()).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved_entry == plugins_root or plugins_root in resolved_entry.parents:
                while entry in sys.path:
                    sys.path.remove(entry)
        gc.collect()

    def stop_plugins(self) -> None:
        for plugin in self.plugins:
            try:
                plugin.stop()
            except Exception as exc:  # noqa: BLE001
                self.errors.append(
                    f"Stop failed for {getattr(plugin, 'plugin_name', plugin.__class__.__name__)}: {exc}"
                )


    def get_plugins(self) -> list[PluginBase]:
        return list(self.plugins)

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

    def _build_context(
        self,
        plugin_dir: Path,
        manifest: dict | None = None,
    ) -> PluginContext:
        if manifest is None:
            manifest = self._load_manifest(plugin_dir / "manifest.json")
        entry_name = str(manifest.get("entry", "plugin.py")).strip() or "plugin.py"
        plugin_root = plugin_dir.resolve()
        entry_file = (plugin_dir / entry_name).resolve()
        if entry_file != plugin_root and plugin_root not in entry_file.parents:
            raise ValueError("Entry file must be inside the plugin directory")
        if not entry_file.exists():
            raise FileNotFoundError(f"Entry file not found: {entry_name}")

        plugin_id = str(manifest.get("id", plugin_dir.name))
        plugin_name = str(manifest.get("name", plugin_dir.name))
        source_settings_file = self._resolve_settings_file(plugin_dir, manifest)
        if source_settings_file != plugin_root and plugin_root not in source_settings_file.parents:
            raise ValueError("Settings file must be inside the plugin directory")
        source_relative = source_settings_file.relative_to(plugin_root)
        plugin_data_dir = (self.data_dir / plugin_dir.name).resolve()
        data_root = self.data_dir.resolve()
        if plugin_data_dir != data_root and data_root not in plugin_data_dir.parents:
            raise ValueError("Plugin data directory must be inside the data directory")
        settings_file = (plugin_data_dir / source_relative).resolve()
        if settings_file != plugin_data_dir and plugin_data_dir not in settings_file.parents:
            raise ValueError("Settings file must be inside the plugin data directory")
        legacy_plugin_dir = (
            self.legacy_data_dir / plugin_dir.name
            if self.legacy_data_dir is not None
            else None
        )
        if not settings_file.exists():
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            legacy_settings_file = (
                legacy_plugin_dir / source_relative
                if legacy_plugin_dir is not None
                else None
            )
            if legacy_settings_file is not None and legacy_settings_file.is_file():
                shutil.copy2(legacy_settings_file, settings_file)
            elif source_settings_file.is_file() and source_settings_file != settings_file:
                shutil.copy2(source_settings_file, settings_file)
            else:
                settings_file.write_text("{}\n", encoding="utf-8")
        if legacy_plugin_dir is not None:
            legacy_cache = legacy_plugin_dir / "cache"
            target_cache = plugin_data_dir / "cache"
            if legacy_cache.is_dir() and not target_cache.exists():
                shutil.copytree(legacy_cache, target_cache)

        return PluginContext(
            plugin_id=plugin_id,
            plugin_name=plugin_name,
            plugin_dir=plugin_dir.resolve(),
            entry_file=entry_file,
            settings_file=settings_file.resolve(),
            manifest=manifest,
            data_dir=plugin_data_dir,
            get_assigned_slots=self.get_assigned_slots,
            invoke_assigned_slot=self.invoke_assigned_slot,
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
        self._plugin_module_names.add(module_name)
        try:
            spec.loader.exec_module(module)
            plugin_class = getattr(module, "Plugin", None)
            if plugin_class is None:
                sys.modules.pop(module_name, None)
                self._plugin_module_names.discard(module_name)
                return None

            plugin = self._construct_plugin(plugin_class, context)
            if not isinstance(plugin, PluginBase):
                raise TypeError("Plugin class must inherit PluginBase")
            return plugin
        except Exception:
            sys.modules.pop(module_name, None)
            self._plugin_module_names.discard(module_name)
            raise

    def _construct_plugin(self, plugin_class: type, context: PluginContext) -> PluginBase:
        try:
            signature = inspect.signature(plugin_class)
        except (TypeError, ValueError):
            signature = None

        if signature is not None:
            params = list(signature.parameters.values())
            context_param = signature.parameters.get("context")
            if context_param is not None and context_param.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                return plugin_class(context=context)
            if params and params[0].kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ) and params[0].name == "context":
                return plugin_class(context)

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
