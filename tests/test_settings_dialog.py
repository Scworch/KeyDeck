from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QContextMenuEvent, QIcon, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtWidgets import QMessageBox

from keydeck.config import AppSettings, DeckPage
from keydeck.plugin_api import Action, PluginBase
from keydeck.plugin_manager import PluginInfo
from keydeck.ui.controls import ToggleSwitch
from keydeck.ui.deck_button import DeckButtonWidget
from keydeck.ui.deck_window import DeckWindow
from keydeck.ui.settings_dialog import (
    ActionPickerDialog,
    SettingsDialog,
)
from keydeck.ui.theme import apply_dark_theme


class SamplePlugin(PluginBase):
    plugin_id = "sample"
    plugin_name = "Sample plugin"

    def __init__(self) -> None:
        super().__init__()
        self.settings_opened = False

    def open_settings(self) -> None:
        self.settings_opened = True


class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_grid_dimensions_are_saved_per_page(self) -> None:
        settings = AppSettings(
            pages=[
                DeckPage(name="Main", rows=2, columns=3),
                DeckPage(name="Secondary", rows=4, columns=2),
            ]
        )
        dialog = SettingsDialog(settings, [])
        try:
            dialog.rows_spin.setValue(3)
            dialog.page_list.setCurrentRow(1)
            dialog.columns_spin.setValue(5)

            saved = dialog.to_settings()

            self.assertEqual((saved.pages[0].rows, saved.pages[0].columns), (3, 3))
            self.assertEqual((saved.pages[1].rows, saved.pages[1].columns), (4, 5))
            self.assertEqual(dialog.preview_page_title.text(), "Secondary")
        finally:
            dialog.close()

    def test_release_build_shows_uninstall_confirmation_with_data_preserved_by_default(self) -> None:
        dialog = None
        with patch("keydeck.ui.settings_dialog.sys.frozen", True, create=True):
            dialog = SettingsDialog(AppSettings(), [])
        checkboxes = []
        set_checkbox = QMessageBox.setCheckBox

        def capture_checkbox(message_box, checkbox) -> None:
            checkboxes.append(checkbox)
            set_checkbox(message_box, checkbox)

        try:
            with (
                patch.object(QMessageBox, "setCheckBox", capture_checkbox),
                patch.object(
                    QMessageBox,
                    "exec",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                dialog._confirm_uninstall()

            self.assertEqual(len(checkboxes), 1)
            self.assertTrue(checkboxes[0].isChecked())
            self.assertTrue(dialog.uninstall_preserve_user_data)
        finally:
            dialog.close()

    def test_uninstall_confirmation_can_choose_to_delete_user_data(self) -> None:
        with patch("keydeck.ui.settings_dialog.sys.frozen", True, create=True):
            dialog = SettingsDialog(AppSettings(), [])
        set_checkbox = QMessageBox.setCheckBox

        def uncheck_data_box(message_box, checkbox) -> None:
            checkbox.setChecked(False)
            set_checkbox(message_box, checkbox)

        try:
            with (
                patch.object(QMessageBox, "setCheckBox", uncheck_data_box),
                patch.object(
                    QMessageBox,
                    "exec",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                dialog._confirm_uninstall()

            self.assertFalse(dialog.uninstall_preserve_user_data)
        finally:
            dialog.close()

    def test_application_icon_is_applied_to_top_level_windows(self) -> None:
        icon = QIcon(str(Path(__file__).resolve().parents[1] / "icons" / "keydeck.ico"))
        previous_icon = self.app.windowIcon()
        self.app.setWindowIcon(icon)
        dialog = SettingsDialog(AppSettings(), [])
        deck = DeckWindow(AppSettings(), [])
        try:
            self.assertFalse(icon.isNull())
            self.assertEqual(dialog.windowIcon().cacheKey(), icon.cacheKey())
            self.assertEqual(deck.windowIcon().cacheKey(), icon.cacheKey())
        finally:
            dialog.close()
            deck.close()
            self.app.setWindowIcon(previous_icon)

    def test_action_search_selects_a_visible_match(self) -> None:
        actions = [
            Action(action_id="sample.alpha", title="Alpha", callback=lambda: None),
            Action(action_id="sample.beta", title="Beta", callback=lambda: None),
        ]
        dialog = ActionPickerDialog(1, "sample.alpha", actions)
        try:
            dialog.search_edit.setText("beta")

            selected = dialog.list_widget.currentItem()
            self.assertIsNotNone(selected)
            self.assertEqual(selected.data(Qt.UserRole), "sample.beta")
            self.assertFalse(selected.isHidden())
        finally:
            dialog.close()

    def test_toggle_switch_responds_to_mouse_and_keyboard(self) -> None:
        toggle = ToggleSwitch("Enable feature")
        toggle.resize(220, 36)
        toggle.show()
        try:
            QTest.mouseClick(toggle, Qt.MouseButton.LeftButton, pos=toggle.rect().center())
            self.assertTrue(toggle.isChecked())

            toggle.setFocus()
            QTest.keyClick(toggle, Qt.Key.Key_Space)
            self.assertFalse(toggle.isChecked())
        finally:
            toggle.close()

    def test_toggle_switch_wraps_long_labels_without_wide_minimum_size(self) -> None:
        toggle = ToggleSwitch(
            "A long setting label that should wrap instead of widening the settings page"
        )

        self.assertLess(toggle.minimumSizeHint().width(), 200)
        self.assertGreater(toggle.heightForWidth(180), toggle.heightForWidth(360))

    def test_deck_keys_keep_their_configured_size_with_global_theme(self) -> None:
        previous_stylesheet = self.app.styleSheet()
        apply_dark_theme(self.app)
        action = Action(
            action_id="sample.run",
            title="Sample",
            callback=lambda: None,
            plugin_id="sample",
        )
        try:
            for button_size in ("small", "medium", "large"):
                with self.subTest(button_size=button_size):
                    settings = AppSettings(
                        button_size=button_size,
                        pages=[DeckPage(slot_actions=["sample.run"])],
                    )
                    deck = DeckWindow(settings, [action])
                    deck.show()
                    self.app.processEvents()
                    try:
                        button = deck.grid_layout.itemAt(0).widget().button
                        expected_size = deck.settings.button_pixels()

                        self.assertEqual(button.width(), expected_size)
                        self.assertEqual(button.height(), expected_size)
                    finally:
                        deck.close()
        finally:
            self.app.setStyleSheet(previous_stylesheet)

    def test_deck_hides_unassigned_buttons_and_is_not_always_on_top(self) -> None:
        deck = DeckWindow(
            AppSettings(
                rows=1,
                columns=4,
                pages=[DeckPage(rows=1, columns=4, slot_actions=["sample.run", None, None, None])],
            ),
            [
                Action(
                    action_id="sample.run",
                    title="Sample",
                    callback=lambda: None,
                    plugin_id="sample",
                )
            ],
        )
        try:
            visible_buttons = deck.grid_widget.findChildren(DeckButtonWidget)

            self.assertEqual(len(visible_buttons), 1)
            self.assertFalse(deck.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            self.assertEqual(deck.grid_layout.count(), 1)
        finally:
            deck.close()

    def test_plugin_assignment_is_unique_across_pages(self) -> None:
        settings = AppSettings.from_dict(
            {
                "pages": [
                    {
                        "name": "First",
                        "rows": 1,
                        "columns": 1,
                        "slot_actions": ["SteamLauncher.launch"],
                        "slot_settings": {"0": {"profile": "primary"}},
                    },
                    {
                        "name": "Second",
                        "rows": 1,
                        "columns": 1,
                        "slot_actions": ["SteamLauncher.launch"],
                        "slot_settings": {"0": {"profile": "secondary"}},
                        "slot_overrides": {"0": {"title": "Duplicate"}},
                    },
                ]
            }
        )

        self.assertEqual(settings.pages[0].slot_actions[0], "SteamLauncher.launch")
        self.assertIsNone(settings.pages[1].slot_actions[0])
        self.assertEqual(settings.pages[0].slot_settings["0"]["profile"], "primary")
        self.assertNotIn("0", settings.pages[1].slot_settings)
        self.assertNotIn("0", settings.pages[1].slot_overrides)

    def test_legacy_discord_action_migrates_its_mode_into_button_settings(self) -> None:
        settings = AppSettings(
            pages=[
                DeckPage(
                    slot_actions=["DiscordConnect.mute"],
                    slot_settings={"0": {"custom": "kept"}},
                )
            ]
        )

        changed = settings.normalize_action_ids(
            {"DiscordConnect.control"},
            aliases={"DiscordConnect.mute": "DiscordConnect.control"},
            alias_settings_defaults={
                "DiscordConnect.mute": {"mode": "mute"}
            },
        )

        self.assertTrue(changed)
        self.assertEqual(
            settings.pages[0].slot_actions[0],
            "DiscordConnect.control",
        )
        self.assertEqual(
            settings.pages[0].slot_settings["0"],
            {"mode": "mute", "custom": "kept"},
        )

    def test_plugin_settings_have_plugin_button_and_appearance_tabs(self) -> None:
        action = Action(
            action_id="sample.run",
            title="Sample",
            callback=lambda: None,
            plugin_id="sample",
            action_settings_callback=lambda _slot, settings: settings,
        )
        settings = AppSettings(
            pages=[DeckPage(slot_actions=["sample.run"])],
        )
        dialog = SettingsDialog(settings, [action], plugins=[SamplePlugin()])
        try:
            self.assertEqual(
                [
                    dialog.plugin_detail_tabs.tabText(index)
                    for index in range(dialog.plugin_detail_tabs.count())
                ],
                ["Plugin", "Button", "Button Appearance"],
            )
            dialog._open_button_appearance(0)
            dialog.appearance_title_edit.setText("Custom label")
            dialog._apply_plugin_button_appearance()

            self.assertEqual(
                dialog.to_settings().pages[0].slot_overrides["0"]["title"],
                "Custom label",
            )
        finally:
            dialog.close()

    def test_settings_dialog_keeps_theme_when_parented_to_deck(self) -> None:
        previous_stylesheet = self.app.styleSheet()
        apply_dark_theme(self.app)
        deck = DeckWindow(AppSettings(), [])
        dialog = SettingsDialog(AppSettings(), [], parent=deck)
        dialog.show()
        self.app.processEvents()
        try:
            background = dialog.grab().toImage().pixelColor(740, 100).name()
            preview_background = (
                dialog.preview_scroll.viewport()
                .grab()
                .toImage()
                .pixelColor(5, 5)
                .name()
            )

            self.assertEqual(background, "#262626")
            self.assertEqual(preview_background, "#242424")
        finally:
            dialog.close()
            deck.close()
            self.app.setStyleSheet(previous_stylesheet)

    def test_settings_icon_is_unframed_and_centered(self) -> None:
        previous_stylesheet = self.app.styleSheet()
        apply_dark_theme(self.app)
        deck = DeckWindow(AppSettings(), [])
        deck.show()
        self.app.processEvents()
        try:
            button = deck.settings_button
            image = deck.grab().toImage()
            rect = button.geometry()
            self.assertEqual(
                image.pixelColor(rect.left(), rect.top()).name(),
                "#262626",
            )

            ink = [
                (x, y)
                for y in range(rect.top(), rect.bottom() + 1)
                for x in range(rect.left(), rect.right() + 1)
                if (
                    (color := image.pixelColor(x, y)).red() > 220
                    and color.green() > 220
                    and color.blue() > 220
                )
            ]
            self.assertTrue(ink)
            center_x = (min(x for x, _ in ink) + max(x for x, _ in ink)) / 2
            center_y = (min(y for _, y in ink) + max(y for _, y in ink)) / 2
            self.assertLessEqual(abs(center_x - rect.center().x()), 1)
            self.assertLessEqual(abs(center_y - rect.center().y()), 1)
        finally:
            deck.close()
            self.app.setStyleSheet(previous_stylesheet)

    def test_button_appearance_can_customize_any_plugin_action(self) -> None:
        action = Action(
            action_id="sample.run",
            title="Default plugin title",
            callback=lambda: None,
            plugin_id="sample",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            icon_path = Path(temp_dir) / "custom.png"
            icon = QPixmap(16, 16)
            icon.fill(QColor("#00ff00"))
            self.assertTrue(icon.save(str(icon_path)))
            settings = AppSettings(
                pages=[
                    DeckPage(
                        name="Main",
                        rows=1,
                        columns=1,
                        slot_actions=["sample.run"],
                    )
                ]
            )
            dialog = SettingsDialog(settings, [action])
            deck = None
            try:
                QTest.qWait(10)
                dialog._open_button_appearance(0)
                dialog.appearance_title_edit.setText("Run")
                dialog.appearance_icon_edit.setText(str(icon_path))
                dialog.appearance_image_mode_combo.setCurrentIndex(
                    dialog.appearance_image_mode_combo.findData("fit")
                )
                dialog.appearance_image_zoom_spin.setValue(1.35)
                dialog.appearance_image_offset_x_spin.setValue(7)
                dialog.appearance_image_offset_y_spin.setValue(-5)
                dialog._apply_plugin_button_appearance()

                preview = dialog._button_widgets[0]
                self.assertEqual(preview.title.text(), "Run")
                self.assertFalse(preview.button._avatar.isNull())
                saved = dialog.to_settings()
                self.assertEqual(
                    saved.pages[0].slot_overrides["0"]["title"], "Run"
                )
                self.assertEqual(
                    saved.pages[0].slot_overrides["0"]["icon_path"],
                    str(icon_path),
                )
                self.assertEqual(
                    saved.pages[0].slot_overrides["0"]["image_mode"],
                    "fit",
                )
                self.assertEqual(
                    saved.pages[0].slot_overrides["0"]["image_zoom"],
                    1.35,
                )
                restored = AppSettings.from_dict(saved.to_dict())
                deck = DeckWindow(restored, [action])
                deck.show()
                self.app.processEvents()
                deck_button = deck.grid_layout.itemAt(0).widget()
                self.assertEqual(deck_button.label.text(), "Run")
                self.assertFalse(deck_button.button._avatar.isNull())
                self.assertEqual(deck_button.button._avatar_mode, "fit")
                self.assertEqual(deck_button.button._avatar_zoom, 1.35)
                self.assertEqual(deck_button.button._avatar_offset_x, 7)
                self.assertEqual(deck_button.button._avatar_offset_y, -5)
            finally:
                dialog.close()
                if deck is not None:
                    deck.close()

    def test_button_context_menu_exposes_appearance_settings(self) -> None:
        action = Action(
            action_id="sample.run",
            title="Run",
            callback=lambda: None,
            plugin_id="sample",
        )
        dialog = SettingsDialog(
            AppSettings(
                pages=[
                    DeckPage(
                        name="Main",
                        rows=1,
                        columns=1,
                        slot_actions=["sample.run"],
                    )
                ]
            ),
            [action],
        )
        dialog.show()
        QTest.qWait(10)
        menu_actions: list[str] = []
        button = dialog._button_widgets[0].button

        def capture_menu() -> None:
            menu = next(
                widget
                for widget in self.app.topLevelWidgets()
                if isinstance(widget, QMenu) and widget.isVisible()
            )
            menu_actions.extend(action.text() for action in menu.actions())
            menu.close()

        QTimer.singleShot(0, capture_menu)
        position = QPoint(10, 10)
        QApplication.sendEvent(
            button,
            QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse,
                position,
                button.mapToGlobal(position),
            ),
        )
        try:
            self.assertIn("Button Appearance...", menu_actions)
        finally:
            dialog.close()

    def test_plugin_settings_refresh_action_list(self) -> None:
        plugin = SamplePlugin()
        action = Action(
            action_id="sample.run",
            title="Run",
            callback=lambda: None,
            plugin_id="sample",
        )
        dialog = SettingsDialog(
            AppSettings(),
            [],
            plugins=[plugin],
            refresh_actions_callback=lambda: [action],
        )
        try:
            dialog.configure_plugin_btn.click()

            self.assertTrue(plugin.settings_opened)
            self.assertEqual(dialog.actions, [action])
            self.assertEqual(dialog.plugin_actions_label.text(), "1 active action")
        finally:
            dialog.close()

    def test_reload_refreshes_plugin_details_and_load_issues(self) -> None:
        plugin = SamplePlugin()
        action = Action(
            action_id="sample.run",
            title="Run",
            callback=lambda: None,
            plugin_id="sample",
        )
        dialog = SettingsDialog(
            AppSettings(),
            [],
            reload_plugins_callback=lambda _disabled: (
                [action],
                [plugin],
                ["Broken: missing module"],
                [PluginInfo("sample", "Sample plugin")],
            ),
        )
        try:
            dialog._reload_plugins()

            self.assertEqual(dialog.plugin_list.count(), 1)
            self.assertEqual(dialog.plugin_actions_label.text(), "1 active action")
            self.assertEqual(dialog.plugin_error_list.count(), 1)
            self.assertEqual(dialog.actions, [action])
        finally:
            dialog.close()

    def test_disabled_plugin_is_listed_and_preserves_its_button_assignment(self) -> None:
        settings = AppSettings(
            disabled_plugins=["sample"],
            pages=[DeckPage(slot_actions=["sample.run"])],
        )
        dialog = SettingsDialog(
            settings,
            [],
            available_plugins=[PluginInfo("sample", "Sample plugin")],
        )
        try:
            self.assertEqual(dialog.plugin_list.count(), 1)
            self.assertEqual(dialog.plugin_status_label.text(), "Disabled")
            item = dialog.plugin_list.item(0)
            self.assertEqual(item.text(), "Sample plugin")
            self.assertEqual(item.data(Qt.UserRole + 1), "Disabled")
            self.assertEqual(
                item.icon().pixmap(12, 12).toImage().pixelColor(6, 6).name(),
                "#737373",
            )
            self.assertFalse(dialog.plugin_enabled_toggle.isChecked())
            self.assertEqual(dialog.plugin_enabled_toggle._position, 0.0)

            saved = dialog.to_settings()

            self.assertEqual(saved.disabled_plugins, ["sample"])
            self.assertEqual(saved.pages[0].slot_actions[0], "sample.run")
        finally:
            dialog.close()

    def test_plugin_toggle_updates_state_label_switch_and_order(self) -> None:
        settings = AppSettings(disabled_plugins=["sample", "zeta"])
        plugins = [SamplePlugin()]
        dialog = SettingsDialog(
            settings,
            [],
            plugins=plugins,
            available_plugins=[
                PluginInfo("sample", "Sample plugin"),
                PluginInfo("other", "Other plugin"),
                PluginInfo("zeta", "Zeta plugin"),
            ],
        )
        try:
            self.assertEqual(
                dialog.plugin_list.item(0).data(Qt.UserRole),
                "other",
            )
            dialog.plugin_list.setCurrentRow(1)
            self.assertFalse(dialog.plugin_enabled_toggle.isChecked())

            dialog.plugin_enabled_toggle.setChecked(True)

            self.assertEqual(dialog.plugin_status_label.text(), "Enabled")
            self.assertTrue(dialog.plugin_enabled_toggle.isChecked())
            self.assertEqual(dialog.plugin_enabled_toggle._position, 1.0)
            self.assertEqual(dialog.plugin_list.item(2).data(Qt.UserRole), "zeta")
            self.assertEqual(dialog.plugin_list.item(1).data(Qt.UserRole + 1), "Enabled")
            self.assertEqual(dialog.plugin_list.item(2).data(Qt.UserRole + 1), "Disabled")
            self.assertEqual(
                dialog.plugin_list.item(1).icon().pixmap(12, 12).toImage().pixelColor(6, 6).name(),
                "#42c783",
            )
            self.assertEqual(dialog.to_settings().disabled_plugins, ["zeta"])
        finally:
            dialog.close()

    def test_plugin_settings_button_edits_multitool_assigned_sequence(self) -> None:
        action = Action(
            action_id="MultiTool.run",
            title="MultiTool",
            callback=lambda: None,
            plugin_id="MultiTool",
            plugin_settings_enabled=False,
            action_settings_callback=lambda _slot, _settings: {
                "steps": [{"type": "url", "value": "https://example.com"}]
            },
        )
        settings = AppSettings(
            pages=[DeckPage(slot_actions=["MultiTool.run"], slot_settings={"0": {}})]
        )
        dialog = SettingsDialog(
            settings,
            [action],
            available_plugins=[PluginInfo("MultiTool", "MultiTool")],
        )
        try:
            self.assertEqual(
                dialog.configure_plugin_btn.text(),
                "Configure assigned button",
            )
            dialog.configure_plugin_btn.click()

            self.assertEqual(
                dialog.to_settings().pages[0].slot_settings["0"]["steps"],
                [{"type": "url", "value": "https://example.com"}],
            )
        finally:
            dialog.close()

    def test_unknown_action_from_disabled_plugin_is_not_removed(self) -> None:
        settings = AppSettings(
            disabled_plugins=["sample"],
            pages=[DeckPage(slot_actions=["sample.run"])],
        )

        changed = settings.normalize_action_ids(set(), preserved_plugin_ids={"sample"})

        self.assertFalse(changed)
        self.assertEqual(settings.pages[0].slot_actions[0], "sample.run")

    def test_unavailable_plugin_action_is_preserved_in_settings_dialog(self) -> None:
        settings = AppSettings(
            pages=[DeckPage(rows=1, columns=1, slot_actions=["LegacyPlugin.run"])]
        )
        dialog = SettingsDialog(settings, [])
        try:
            saved = dialog.to_settings()

            self.assertEqual(saved.pages[0].slot_actions[0], "LegacyPlugin.run")
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
