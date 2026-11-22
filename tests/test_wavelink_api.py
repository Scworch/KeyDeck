from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugins" / "WaveLink"
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))
import wavelink_api

PLUGIN_SPEC = importlib.util.spec_from_file_location(
    "wavelink_control_plugin_test",
    PLUGIN_DIR / "plugin.py",
)
assert PLUGIN_SPEC is not None and PLUGIN_SPEC.loader is not None
wavelink_plugin = importlib.util.module_from_spec(PLUGIN_SPEC)
sys.modules[PLUGIN_SPEC.name] = wavelink_plugin
PLUGIN_SPEC.loader.exec_module(wavelink_plugin)

from PySide6.QtWidgets import QApplication


class FakeWebSocket:
    def __init__(self, *, include_stream: bool = True) -> None:
        self.connected = True
        self.requests: list[dict] = []
        self.responses: list[str] = []
        self.channel_mixes = [{"id": "personal", "level": 0.65}]
        if include_stream:
            self.channel_mixes.append({"id": "stream", "level": 0.4})

    def settimeout(self, _timeout: float) -> None:
        pass

    def send(self, raw_request: str) -> None:
        request = json.loads(raw_request)
        self.requests.append(request)
        method = request["method"]
        result = {
            "getApplicationInfo": {
                "appID": "EWL",
                "version": "3.5.0.5259",
                "interfaceRevision": 3,
            },
            "getChannels": {
                "channels": [
                    {
                        "id": "channel-music",
                        "name": "Music",
                        "mixes": self.channel_mixes,
                    }
                ]
            },
            "getMixes": {
                "mixes": [
                    {"id": "personal", "name": "Personal Mix"},
                    {"id": "stream", "name": "Stream Mix"},
                ]
            },
            "setChannel": {},
        }[method]
        self.responses.append(
            json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result})
        )

    def recv(self) -> str:
        return self.responses.pop(0)

    def close(self) -> None:
        self.connected = False


class WaveLinkApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_api_factory_keeps_legacy_and_defaults_to_35(self) -> None:
        self.assertIsInstance(wavelink_api.create_client(), wavelink_api.WaveLink35Client)
        with patch.object(wavelink_api, "WaveLinkClient") as legacy_client:
            self.assertIs(wavelink_api.create_client("2.0.6"), legacy_client.return_value)

    def test_settings_dialog_defaults_to_35_and_allows_legacy_api(self) -> None:
        plugin = wavelink_plugin.Plugin()
        dialog = wavelink_plugin.WaveLinkSettingsDialog(plugin, ["Music"], None)
        try:
            self.assertEqual(dialog.get_settings()["api_version"], "3.5")
            dialog.api_version_combo.setCurrentIndex(1)
            self.assertEqual(dialog.get_settings()["api_version"], "2.0.6")
        finally:
            dialog.close()

    def test_wave_link_35_reads_and_sets_personal_mix_level(self) -> None:
        client = wavelink_api.WaveLink35Client()
        client._candidate_ports = lambda: [12713]
        fake_socket = FakeWebSocket()

        with patch.object(
            wavelink_api.socket,
            "create_connection",
            return_value=MagicMock(),
        ), patch("websocket.create_connection", return_value=fake_socket) as connect:
            self.assertEqual(client.get_volume("Music"), 65)
            self.assertEqual(client.get_volume("Music", mix="stream"), 40)
            self.assertEqual(client.set_volume("Music", 73), 73)

        connect.assert_called_once_with(
            "ws://127.0.0.1:12713",
            timeout=3.0,
            origin="streamdeck://",
        )
        set_request = next(
            request for request in fake_socket.requests if request["method"] == "setChannel"
        )
        self.assertEqual(
            set_request["params"],
            {
                "id": "channel-music",
                "mixes": [{"id": "personal", "level": 0.73}],
            },
        )
        client.disconnect()

    def test_wave_link_35_selects_stream_mix_and_rejects_unrouted_channel(self) -> None:
        client = wavelink_api.WaveLink35Client()
        fake_socket = FakeWebSocket(include_stream=False)

        with patch.object(
            wavelink_api.socket,
            "create_connection",
            return_value=MagicMock(),
        ), patch("websocket.create_connection", return_value=fake_socket):
            with self.assertRaisesRegex(wavelink_api.WaveLinkError, "not routed"):
                client.get_volume("Music", mix="stream")
        client.disconnect()


if __name__ == "__main__":
    unittest.main()
