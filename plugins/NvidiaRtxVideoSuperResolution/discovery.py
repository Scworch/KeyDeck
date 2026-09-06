from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
from typing import Any


NVIDIA_APP_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVIDIA App"
DISPLAY_PLUGIN = NVIDIA_APP_DIR / "CEF" / "plugins" / "Base" / "NvCplDisplayPlugin.dll"
NVCPL_API = NVIDIA_APP_DIR / "NvCpl" / "NvCpl.dll"
MESSAGEBUS_CONFIG = NVIDIA_APP_DIR / "MessageBus" / "messagebus.conf"
NVCPL_EXPORTS = (
    "NvCplApiIsUxdServiceRunning",
    "NvCplApiInit",
    "NvCplApiGetSetting",
    "NvCplApiSetSetting",
    "NvCplApiExecute",
    "NvCplApiManageState",
    "NvCplApiClose",
)
COMMANDS = (
    "GetSuperResolutionInfo",
    "GetSuperResolutionCurrentStatus",
    "SetSuperResolutionValue",
    "GetSuperResolutionGpuUtilization",
    "SetSuperResolutionGpuUtilization",
    "GetSuperResolutionIndicatorStatus",
    "SetSuperResolutionIndicatorStatus",
    "GetRTXVideoFlags",
    "SetRTXVSRFlags",
    "CommitState",
    "CancelState",
    "RestoreDefaultVideoSettings",
)


def _named_exports(path: Path) -> list[str]:
    """Read PE export names without loading or invoking the DLL."""
    data = path.read_bytes()
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    section_count = int.from_bytes(data[pe_offset + 6:pe_offset + 8], "little")
    optional_size = int.from_bytes(data[pe_offset + 20:pe_offset + 22], "little")
    optional = pe_offset + 24
    magic = int.from_bytes(data[optional:optional + 2], "little")
    data_directory = optional + (112 if magic == 0x20B else 96)
    export_rva = int.from_bytes(data[data_directory:data_directory + 4], "little")
    section_table = optional + optional_size
    sections: list[tuple[int, int, int]] = []
    for index in range(section_count):
        offset = section_table + index * 40
        virtual_size = int.from_bytes(data[offset + 8:offset + 12], "little")
        virtual_address = int.from_bytes(data[offset + 12:offset + 16], "little")
        raw_size = int.from_bytes(data[offset + 16:offset + 20], "little")
        raw_offset = int.from_bytes(data[offset + 20:offset + 24], "little")
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))

    def rva_to_offset(rva: int) -> int:
        for address, size, raw_offset in sections:
            if address <= rva < address + size:
                return raw_offset + rva - address
        raise ValueError(f"RVA is outside PE sections: {rva:#x}")

    export_offset = rva_to_offset(export_rva)
    fields = __import__("struct").unpack_from("<IIHHIIIIIII", data, export_offset)
    name_count = fields[7]
    names_rva = fields[9]
    names_offset = rva_to_offset(names_rva)
    exports = []
    for index in range(name_count):
        name_rva = int.from_bytes(data[names_offset + index * 4:names_offset + index * 4 + 4], "little")
        name_offset = rva_to_offset(name_rva)
        end = data.index(0, name_offset)
        exports.append(data[name_offset:end].decode("ascii", errors="replace"))
    return exports


def _processes() -> list[dict[str, Any]]:
    try:
        import psutil
    except ImportError:
        return [{"error": "psutil is not installed"}]

    results = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        name = (process.info.get("name") or "").casefold()
        if "nvidia" in name or "nvcontainer" in name:
            results.append(
                {
                    "pid": process.info.get("pid"),
                    "name": process.info.get("name"),
                    "path": process.info.get("exe"),
                }
            )
    return results


def detect() -> dict[str, Any]:
    result: dict[str, Any] = {
        "nvidia_app_dir": str(NVIDIA_APP_DIR),
        "display_plugin": str(DISPLAY_PLUGIN),
        "nv_cpl_api": str(NVCPL_API),
        "messagebus_config": str(MESSAGEBUS_CONFIG),
        "processes": _processes(),
        "files": {},
        "embedded_methods": list(COMMANDS),
        "transport": "QUERY_IPC_EXTENSION_MESSAGE via CrimsonNative/NvCplDisplayPlugin",
        "write_support": False,
        "write_support_reason": (
            "The display plugin has no exported VSR setter; the methods are embedded "
            "in the NVIDIA App IPC command registry. The transport envelope is not "
            "implemented here because its named-pipe protocol is not verified."
        ),
    }
    for path in (DISPLAY_PLUGIN, NVCPL_API, MESSAGEBUS_CONFIG):
        if path.exists():
            stat = path.stat()
            item: dict[str, Any] = {
                "exists": True,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            }
            if path == DISPLAY_PLUGIN:
                try:
                    item["exports"] = _named_exports(path)
                except (OSError, ValueError) as exc:
                    item["export_error"] = f"{type(exc).__name__}: {exc}"
            elif path == NVCPL_API:
                try:
                    exports = _named_exports(path)
                    item["exports"] = exports
                    item["required_exports"] = list(NVCPL_EXPORTS)
                    item["missing_required_exports"] = [
                        name for name in NVCPL_EXPORTS if name not in exports
                    ]
                except (OSError, ValueError) as exc:
                    item["export_error"] = f"{type(exc).__name__}: {exc}"
            else:
                item["configuration"] = json.loads(path.read_text(encoding="utf-8"))
            result["files"][str(path)] = item
        else:
            result["files"][str(path)] = {"exists": False}
    return result
