from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from keydeck.plugin_manager import PluginManager
from keydeck.plugin_api import PluginContext
from keydeck.plugin_api import Action
from keydeck.config import AppSettings
from keydeck.ui.deck_button import DeckButtonWidget
from keydeck.ui.deck_window import DeckWindow
from plugins.DiscordConnect.plugin import Plugin
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from plugins.DiscordConnect.discordconnect_rpc import (
    DiscordRpcError,
    DiscordRpcWorker,
    consume_rpc_frames,
    encode_rpc_frame,
    filter_guilds,
    filter_voice_channels,
    make_pkce_pair,
)
from plugins.DiscordConnect.discordconnect_secure_store import SecureCredentialStore


class DiscordConnectTests(unittest.TestCase):
    def test_dynamic_action_labels_and_generated_button_artwork(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin_dir = Path(__file__).resolve().parents[1] / "plugins" / "DiscordConnect"
            context = PluginContext(
                plugin_id="DiscordConnect",
                plugin_name="Discord Connect",
                plugin_dir=plugin_dir,
                entry_file=plugin_dir / "plugin.py",
                settings_file=root / "settings.json",
                manifest={"id": "DiscordConnect"},
                data_dir=root / "data",
            )
            plugin = Plugin(context)
            plugin._connection_state = "connected"
            plugin._voice_settings = {"mute": True, "deaf": False}
            actions = {action.action_id: action for action in plugin.actions()}

            self.assertEqual(
                actions["DiscordConnect.control"].action_title_callback(
                    0, {"mode": "mute"}
                ),
                "Unmute",
            )
            self.assertEqual(
                actions["DiscordConnect.control"].action_title_callback(
                    0, {"mode": "deafen"}
                ),
                "Deafen",
            )
            settings = AppSettings().clamp()
            settings.pages[0].slot_actions[0] = "DiscordConnect.control"
            settings.pages[0].slot_settings["0"] = {"mode": "mute"}
            deck = DeckWindow(settings, [actions["DiscordConnect.control"]])
            button = deck.grid_widget.findChildren(DeckButtonWidget)[0]
            self.assertEqual(button.label.text(), "Unmute")
            mute_icon = Path(
                actions["DiscordConnect.control"].action_icon_callback(
                    0, {"mode": "mute"}
                )
            )
            self.assertIn("#ED4245", mute_icon.read_text(encoding="utf-8"))
            join_icon = Path(
                actions["DiscordConnect.control"].action_icon_callback(
                    0,
                    {
                        "mode": "join",
                        "guild_id": "12345678901234567",
                        "guild_name": "Test server",
                        "channel_id": "12345678901234568",
                        "channel_name": "Long voice channel name",
                    },
                )
            )
            rendered = QImage(str(join_icon))

            self.assertFalse(rendered.isNull())
            self.assertEqual((rendered.width(), rendered.height()), (512, 512))
            deck.close()
            self.assertIsNotNone(app)

    def test_plugin_loads_through_the_existing_plugin_manager(self) -> None:
        source = Path(__file__).resolve().parents[1] / "plugins" / "DiscordConnect"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin_dir = root / "plugins" / "DiscordConnect"
            plugin_dir.mkdir(parents=True)
            for name in (
                "plugin.py",
                "discordconnect_rpc.py",
                "discordconnect_secure_store.py",
                "mic.svg",
                "mic-off.svg",
                "headphones.svg",
                "headphone-off.svg",
            ):
                shutil.copy2(source / name, plugin_dir / name)
            shutil.copy2(source / "manifest.json", plugin_dir / "manifest.json")
            manager = PluginManager(
                root / "plugins",
                data_dir=root / "data",
                refresh_actions=lambda: None,
            )

            manager.load_plugins()

            self.assertEqual(manager.errors, [])
            self.assertEqual(
                [action.action_id for action in manager.all_actions()],
                ["DiscordConnect.control"],
            )
            manager.unload_plugins()

    def test_voice_channel_filter_keeps_only_valid_guild_voice_channels(self) -> None:
        channels = filter_voice_channels(
            {
                "channels": [
                    {"id": "12345678901234567", "name": "General", "type": 2},
                    {"id": "12345678901234568", "name": "Stage", "type": 13},
                    {"id": "12345678901234569", "name": "Text", "type": 0},
                    {"id": "not-an-id", "name": "Invalid", "type": 2},
                ]
            }
        )

        self.assertEqual(
            channels,
            [{"id": "12345678901234567", "name": "General", "type": 2}],
        )

    def test_guild_filter_preserves_stable_ids_and_optional_icon_urls(self) -> None:
        guilds = filter_guilds(
            [
                {"id": "12345678901234567", "name": "Guild", "icon_url": "https://cdn.discordapp.com/icons/x.png"},
                {"id": "bad", "name": "Invalid"},
                {"id": "12345678901234568", "name": ""},
            ]
        )

        self.assertEqual(
            guilds,
            [
                {
                    "id": "12345678901234567",
                    "name": "Guild",
                    "icon_url": "https://cdn.discordapp.com/icons/x.png",
                }
            ],
        )

    def test_rpc_frame_decoder_handles_partial_and_consecutive_frames(self) -> None:
        first = encode_rpc_frame(1, {"cmd": "GET_GUILDS", "data": {"guilds": []}})
        second = encode_rpc_frame(1, {"cmd": "GET_CHANNELS", "data": {"channels": []}})
        pending = bytearray(first[:5])

        self.assertEqual(consume_rpc_frames(pending), [])

        pending.extend(first[5:] + second)
        frames = consume_rpc_frames(pending)

        self.assertEqual(
            [payload["cmd"] for _opcode, payload in frames],
            ["GET_GUILDS", "GET_CHANNELS"],
        )
        self.assertEqual(pending, bytearray())

    def test_pkce_uses_s256_url_safe_challenge(self) -> None:
        verifier, challenge = make_pkce_pair()

        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertNotIn("=", challenge)
        self.assertTrue(all(character.isalnum() or character in "-_" for character in challenge))

    def test_toggle_uses_confirmed_voice_state_and_does_not_update_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = DiscordRpcWorker(
                "12345678901234567",
                SecureCredentialStore(root / "credentials.dpapi"),
                root / "cache",
            )
            worker._voice_settings = {"mute": False, "deaf": False}
            calls: list[tuple[str, dict]] = []

            def succeed(command: str, args: dict, **_kwargs) -> dict:
                calls.append((command, args))
                if command == "SET_VOICE_SETTINGS":
                    return {"mute": args["mute"], "deaf": False}
                return {"mute": True, "deaf": False}

            worker._rpc_command = succeed
            worker._handle_rpc_request("toggle_mute", {})

            self.assertIn(("SET_VOICE_SETTINGS", {"mute": True}), calls)
            self.assertTrue(worker._voice_settings["mute"])

            worker._voice_settings = {"mute": False, "deaf": False}

            def reject(command: str, _args: dict, **_kwargs):
                if command == "SET_VOICE_SETTINGS":
                    raise DiscordRpcError("Discord rejected the RPC request.")
                return {"mute": False, "deaf": False}

            worker._rpc_command = reject
            with self.assertRaises(DiscordRpcError):
                worker._handle_rpc_request("toggle_mute", {})
            self.assertFalse(worker._voice_settings["mute"])

    def test_join_queries_selected_channel_after_rpc_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = DiscordRpcWorker(
                "12345678901234567",
                SecureCredentialStore(root / "credentials.dpapi"),
                root / "cache",
            )
            calls: list[tuple[str, dict]] = []
            selected = {
                "id": "12345678901234568",
                "name": "General",
                "guild_id": "12345678901234567",
            }

            def response(command: str, args: dict, **_kwargs):
                calls.append((command, args))
                return selected if command == "GET_SELECTED_VOICE_CHANNEL" else {}

            worker._rpc_command = response
            result = worker._handle_rpc_request(
                "join",
                {"channel_id": selected["id"], "force": True},
            )

            self.assertEqual(
                calls,
                [
                    ("SELECT_VOICE_CHANNEL", {"channel_id": selected["id"], "force": True}),
                    ("GET_SELECTED_VOICE_CHANNEL", {}),
                ],
            )
            self.assertEqual(result["channel"], selected)

    def test_join_fails_when_discord_does_not_confirm_selected_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = DiscordRpcWorker(
                "12345678901234567",
                SecureCredentialStore(root / "credentials.dpapi"),
                root / "cache",
            )
            worker._rpc_command = lambda command, _args, **_kwargs: (
                {"id": "12345678901234569"}
                if command == "GET_SELECTED_VOICE_CHANNEL"
                else {}
            )

            with self.assertRaisesRegex(DiscordRpcError, "did not confirm"):
                worker._handle_rpc_request(
                    "join",
                    {"channel_id": "12345678901234568"},
                )

    def test_leave_checks_discord_state_after_disconnect_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = DiscordRpcWorker(
                "12345678901234567",
                SecureCredentialStore(root / "credentials.dpapi"),
                root / "cache",
            )
            worker._rpc_command = lambda command, _args, **_kwargs: (
                {"id": "12345678901234568"}
                if command == "GET_SELECTED_VOICE_CHANNEL"
                else {}
            )

            with self.assertRaisesRegex(DiscordRpcError, "did not confirm leaving"):
                worker._handle_rpc_request("leave", {})

    def test_refresh_response_without_token_preserves_existing_refresh_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worker = DiscordRpcWorker(
                "12345678901234567",
                SecureCredentialStore(Path(temporary) / "credentials.dpapi"),
                Path(temporary) / "cache",
            )
            worker._credentials = {"refresh_token": "prior-refresh-token"}

            worker._save_token_response(
                {"access_token": "fresh-access-token", "expires_in": 3600}
            )

            self.assertEqual(
                worker._credentials["refresh_token"],
                "prior-refresh-token",
            )

    def test_credential_store_encrypts_before_writing_and_decrypts_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "credentials.dpapi"
            store = SecureCredentialStore(path)

            def transform(data: bytes, *, protect: bool) -> bytes:
                if protect:
                    return b"protected:" + base64.b64encode(data)
                return base64.b64decode(data.removeprefix(b"protected:"))

            with patch(
                "plugins.DiscordConnect.discordconnect_secure_store._dpapi_transform",
                side_effect=transform,
            ):
                store.save({"access_token": "private-token"})
                stored = path.read_bytes()
                loaded = store.load()

            self.assertTrue(stored.startswith(b"protected:"))
            self.assertNotIn(b"private-token", stored)
            self.assertEqual(loaded, {"access_token": "private-token"})


if __name__ == "__main__":
    unittest.main()
