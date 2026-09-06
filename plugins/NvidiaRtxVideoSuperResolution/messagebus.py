from __future__ import annotations


def write_support_status() -> dict[str, object]:
    return {
        "supported": False,
        "reason": (
            "The JavaScript command registry confirms QUERY_IPC_EXTENSION_MESSAGE "
            "to CrimsonNative/NvCplDisplayPlugin, but no verified local named-pipe "
            "request/response framing is available."
        ),
    }
