from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QMessageBox

from keydeck.plugin_api import Action, PluginBase, PluginContext


class Plugin(PluginBase):
    plugin_id = "example_hello"
    plugin_name = "Example Hello"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        self._settings = (
            self.context.load_settings({"hello_message": "Hello from plugins/example_hello"})
            if self.context
            else {"hello_message": "Hello from plugins/example_hello"}
        )

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id="hello_popup",
                title="Hello",
                callback=self.show_hello,
            ),
            Action(
                action_id="time_popup",
                title="Time",
                callback=self.show_time,
            ),
        ]

    def show_hello(self) -> None:
        QMessageBox.information(
            None,
            "KeyDeck",
            str(self._settings.get("hello_message", "Hello from plugins/example_hello")),
        )

    def show_time(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        QMessageBox.information(None, "KeyDeck", f"Local time: {now}")
