import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from masso_core import MassoStatus
from send_to_masso import MainWindow, STYLE


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.window = MainWindow(demo=True)
        self.window.timer.stop()
        self.window.workflow.items.clear()
        self.window.refresh_table()
        self.addCleanup(self.window.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "part.nc"
        self.path.write_text("G0 X0\n")

    def test_new_desktop_runs_without_tkinter(self):
        import sys
        self.assertNotIn("tkinter", sys.modules)
        self.window.show()
        self.app.processEvents()
        self.assertFalse(self.window.send_btn.isEnabled())
        self.assertFalse(self.window.queue_card.isVisible())

    def test_add_move_remove_and_folder_preview(self):
        other = Path(self.temp.name) / "second.tap"
        other.write_text("G0 Y0\n")
        self.window.add_files([str(self.path), str(other)])
        self.assertEqual(self.window.table.rowCount(), 2)
        self.window.table.selectRow(0)
        self.window.move_selected(1)
        self.assertEqual(Path(self.window.workflow.items[1].path).name, "part.nc")
        self.window.folder.setText("/Test/")
        self.assertIn("\\Test\\part.nc", self.window.target_preview.text())
        self.window.remove_selected()
        self.assertEqual(self.window.table.rowCount(), 1)

    def test_render_all_pages_and_log_at_minimum_size(self):
        self.window.resize(1060, 740)
        self.window.show()
        for page in range(self.window.pages.count()):
            self.window.set_page(page)
            self.window.toggle_log(True)
            self.app.processEvents()
            self.assertFalse(self.window.grab().isNull())
            self.assertEqual(self.window.connection_card.isVisible(), page == 0)
        self.window.set_page(0)
        self.assertTrue(self.window.connection_card.isVisible())

    def test_demo_cannot_enable_sending_even_with_ready_status(self):
        self.window.add_files([str(self.path)])
        self.window.client.status = MassoStatus(connected=True, stopped_since=time.monotonic() - 3,
                                               last_packet_time=time.monotonic())
        self.window.refresh_status()
        self.assertFalse(self.window.send_btn.isEnabled())
        self.assertFalse(self.window.connect_btn.isEnabled())

    def test_profiles_required_and_unsaved_address_cannot_connect(self):
        self.window.demo = False
        self.window.config = {"profiles": [], "last_profile": ""}
        self.window.load_profiles()
        self.assertEqual(self.window.page_title.text(), "Profiles")
        self.assertFalse(self.window.connect_btn.isEnabled())
        self.assertFalse(hasattr(self.window, "host"))
        self.window.profile_name.setText("Shop")
        self.window.profile_ip.setText("192.168.1.42")
        with patch.object(self.window.client, "start", create=True) as start, \
             patch.object(self.window, "warn") as warning, \
             patch("send_to_masso.save_config"):
            self.window.toggle_connection()
            start.assert_not_called()
            warning.assert_called_once()
            self.window.save_profile()
            self.assertTrue(self.window.connect_btn.isEnabled())
            self.window.profile_ip.setText("192.168.1.99")
            self.window.toggle_connection()
            start.assert_called_once_with("192.168.1.42")

    def test_default_config_requires_profile_creation(self):
        from masso_core import load_config
        with patch("masso_core.CONFIG_FILE", Path(self.temp.name) / "missing.json"):
            config = load_config()
        self.assertEqual(config["profiles"], [])
        self.assertEqual(config["last_profile"], "")

    def test_profile_selection_defaults_to_first_when_previous_selection_is_missing(self):
        self.window.demo = False
        self.window.config["profiles"] = [
            {"name": "CNC 1", "ip": "192.168.1.41"},
            {"name": "CNC 2", "ip": "192.168.1.42"},
        ]
        for previous in ("", "Deleted profile"):
            self.window.config["last_profile"] = previous
            self.window.load_profiles()
            self.assertEqual(self.window.profile_combo.currentIndex(), 0)
            self.assertEqual(self.window.profile_combo.currentText(), "CNC 1")
            self.assertEqual(self.window.saved_profiles.currentRow(), 0)
            self.assertEqual(self.window.profile_name.text(), "CNC 1")
            self.assertTrue(self.window.connect_btn.isEnabled())
        self.window.config["last_profile"] = "CNC 2"
        self.window.load_profiles()
        self.assertEqual(self.window.profile_combo.currentText(), "CNC 2")
        self.window.config["profiles"] = []
        self.window.load_profiles()
        self.assertEqual(self.window.profile_combo.currentIndex(), -1)
        self.assertEqual(self.window.profile_combo.placeholderText(), "No saved profiles")
        self.assertFalse(self.window.connect_btn.isEnabled())

    def test_save_profile_requires_valid_changes_and_resets_after_save(self):
        save = self.window.profile_buttons[0]
        self.assertFalse(save.isEnabled())
        address = self.window.profile_ip.text()
        self.window.profile_ip.setText("192.168.1.42")
        self.assertTrue(save.isEnabled())
        self.window.refresh_status()
        self.assertTrue(save.isEnabled())
        self.window.profile_ip.setText(address)
        self.assertFalse(save.isEnabled())
        self.window.profile_ip.clear()
        self.assertFalse(save.isEnabled())
        self.window.profile_ip.setText("192.168.1.42")
        self.window.save_profile()
        self.assertFalse(save.isEnabled())
        self.window.new_profile()
        self.assertFalse(save.isEnabled())
        self.assertFalse(self.window.profile_buttons[2].isEnabled())
        self.window.profile_name.setText("CNC 2")
        self.assertFalse(save.isEnabled())
        self.window.profile_ip.setText("192.168.1.43")
        self.assertTrue(save.isEnabled())

    def test_multiple_profiles_select_edit_rename_and_reject_duplicate_names(self):
        self.window.new_profile()
        self.window.profile_name.setText("CNC 2")
        self.window.profile_ip.setText("192.168.1.43")
        self.window.save_profile()
        self.assertEqual(self.window.saved_profiles.count(), 2)
        self.assertEqual(self.window.profile_combo.count(), 2)
        self.assertFalse(self.window.profile_buttons[0].isEnabled())
        self.window.saved_profiles.setCurrentRow(0)
        self.assertEqual(self.window.profile_name.text(), "Workshop MASSO")
        self.assertEqual(self.window.profile_ip.text(), "192.168.1.120")
        self.window.profile_name.setText("CNC 1")
        self.window.save_profile()
        self.assertEqual(len(self.window.config["profiles"]), 2)
        self.assertEqual(self.window.saved_profiles.currentItem().text(), "CNC 1\n192.168.1.120")
        self.window.new_profile()
        self.window.profile_name.setText("CNC 2")
        self.window.profile_ip.setText("192.168.1.99")
        with patch.object(self.window, "warn") as warning:
            self.window.save_profile()
        warning.assert_called_once()
        self.assertEqual(self.window.config["profiles"][1]["ip"], "192.168.1.43")
        self.window.load_profiles()
        self.assertEqual(self.window.saved_profiles.count(), 2)
        self.assertFalse(self.window.profile_buttons[0].isEnabled())

    def test_tool_library_slides_over_queue_and_closes(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.demo = False
        self.window.client.connected = True
        self.window.client.status = MassoStatus(connected=True, last_packet_time=time.monotonic())
        self.window.refresh_status()
        self.assertEqual(self.window.pages.count(), 2)
        self.assertEqual([b.text() for b in self.window.nav_buttons], ["File queue", "Profiles"])
        self.window.set_page(0)
        self.window.show()
        self.app.processEvents()
        self.assertFalse(self.window.tools_pane.isVisible())
        queue_width = self.window.table.width()
        self.window.tools_toggle.click()
        QTest.qWait(260)
        self.assertTrue(self.window.tools_pane.isVisible())
        self.assertTrue(self.window.scan_btn.isVisible())
        self.assertTrue(self.window.export_btn.isVisible())
        self.assertEqual(self.window.table.width(), queue_width)
        self.assertEqual(self.window.tools_pane.geometry().right(), self.window.tools_host.width() - 1)
        self.window.resize(1060, 740)
        self.app.processEvents()
        self.assertEqual(self.window.tools_pane.geometry().right(), self.window.tools_host.width() - 1)
        self.window.tools_close.click()
        QTest.qWait(260)
        self.assertFalse(self.window.tools_pane.isVisible())
        self.assertFalse(self.window.tools_toggle.isChecked())
        self.window.tools_toggle.click()
        QTest.qWait(260)
        QTest.keyClick(self.window.tools_close, Qt.Key.Key_Escape)
        QTest.qWait(260)
        self.assertFalse(self.window.tools_pane.isVisible())
        self.window.tools_toggle.click()
        self.window.set_page(1)
        QTest.qWait(260)
        self.assertFalse(self.window.tools_pane.isVisible())
        self.assertEqual(self.window.page_scroll.verticalScrollBar().value(), 0)

    def test_machine_status_queue_and_tools_only_visible_with_live_connection(self):
        self.window.demo = False
        self.window.show()
        self.window.refresh_status()
        self.assertFalse(self.window.tools_toggle.isVisible())
        self.assertFalse(self.window.queue_card.isVisible())
        self.assertFalse(self.window.status_card.isVisible())
        self.window.toggle_tools_pane(True)
        self.assertFalse(self.window.tools_host.opened)
        self.window.client.connected = True
        self.window.client.status = MassoStatus(connected=True)
        self.window.refresh_status()
        self.assertFalse(self.window.tools_toggle.isVisible())
        self.assertFalse(self.window.queue_card.isVisible())
        self.assertFalse(self.window.status_card.isVisible())
        self.window.client.status.last_packet_time = time.monotonic()
        self.window.refresh_status()
        self.assertTrue(self.window.tools_toggle.isVisible())
        self.assertTrue(self.window.queue_card.isVisible())
        self.assertTrue(self.window.status_card.isVisible())
        with patch("send_to_masso.save_config"):
            self.window.add_files([str(self.path)])
        self.window.tools_toggle.click()
        self.assertTrue(self.window.tools_host.opened)
        self.window.client.connected = False
        self.window.refresh_status()
        self.assertFalse(self.window.tools_toggle.isVisible())
        self.assertFalse(self.window.queue_card.isVisible())
        self.assertFalse(self.window.status_card.isVisible())
        self.assertEqual(len(self.window.workflow.items), 1)
        self.assertFalse(self.window.tools_host.opened)

    def test_live_send_and_worker_events(self):
        self.window.demo = False
        self.window.client.status = MassoStatus(connected=True, stopped_since=time.monotonic() - 3,
                                               last_packet_time=time.monotonic())
        self.window.client.connected = True
        calls = []
        self.window.client.upload_file_async = lambda path, folder, upload_id: calls.append(upload_id)
        with patch("send_to_masso.save_config"):
            self.window.add_files([str(self.path)])
            self.assertTrue(self.window.send_btn.isEnabled())
            self.window.send_queue()
        self.assertEqual(len(calls), 1)
        self.window.events.put(("upload_complete", {"upload_id": calls[0], "filename": "part.nc"}))
        self.window.events.put(("upload_state", False))
        self.window.poll()
        self.assertFalse(self.window.workflow.running)
        self.assertEqual(self.window.workflow.items[0].status, "Done")

    def test_tool_events_and_export(self):
        self.window.events.put(("tool_data", {"tool_index": 3, "tool_name": "End mill"}))
        self.window.events.put(("tools_scan_complete", {"ok": True}))
        self.window.poll()
        self.assertEqual(self.window.tools_table.item(0, 1).text(), "End mill")
        output = Path(self.temp.name) / "tools.txt"
        with patch("send_to_masso.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            self.window.export_tools()
        self.assertIn("End mill", output.read_text())

    def test_connected_profile_changes_preserve_active_identity(self):
        from copy import deepcopy
        self.window.client.connected = True
        self.window.client.host = self.window.profile_combo.currentData()
        active_address = self.window.profile_combo.currentData()
        active_name = self.window.profile_combo.currentText()
        saved = deepcopy(self.window.config)
        self.window.refresh_status()
        self.assertFalse(self.window.profile_name.isEnabled())
        self.assertFalse(self.window.profile_ip.isEnabled())
        self.assertTrue(all(not b.isEnabled() for b in self.window.profile_buttons))
        # Guard callbacks too, even if invoked directly rather than by a button.
        self.window.profile_name.setText("Other machine")
        self.window.profile_ip.setText("192.168.1.121")
        with patch.object(self.window, "warn") as warning:
            self.window.save_profile()
            self.window.new_profile()
            self.window.delete_profile()
        self.assertEqual(warning.call_count, 3)
        self.assertEqual(self.window.config, saved)
        self.assertEqual(self.window.profile_combo.currentData(), active_address)
        self.assertEqual(self.window.profile_combo.currentText(), active_name)
        self.assertEqual(self.window.client.host, active_address)
        self.window.client.connected = False
        self.window.refresh_status()
        self.window.save_profile()
        self.assertEqual(self.window.profile_combo.currentData(), "192.168.1.121")
        self.assertTrue(self.window.profile_name.isEnabled())

    def test_refresh_preserves_all_selected_rows_for_batch_removal(self):
        from PySide6.QtCore import QItemSelectionModel
        paths = [self.path, Path(self.temp.name) / "second.tap", Path(self.temp.name) / "third.nc"]
        for path in paths:
            path.write_text("G0 X0\n")
        self.window.add_files([str(path) for path in paths])
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in (0, 2):
            self.window.table.selectionModel().select(self.window.table.model().index(row, 0), flags)
        selected = self.window.selected_ids()
        self.assertEqual(len(selected), 2)
        self.window.refresh_table()
        self.assertEqual(self.window.selected_ids(), selected)
        self.window.folder.setText("/Changed/")
        self.assertEqual(self.window.selected_ids(), selected)
        self.window.remove_selected()
        self.assertEqual(len(self.window.workflow.items), 1)
        self.assertEqual(Path(self.window.workflow.items[0].path).name, "second.tap")

    def test_busy_queue_blocks_picker_and_dropped_files(self):
        self.window.workflow.running = True
        self.window.refresh_status()
        self.assertFalse(self.window.add_btn.isEnabled())
        with patch.object(self.window, "warn") as warning, \
             patch("send_to_masso.QFileDialog.getOpenFileNames") as picker:
            self.window.choose_files()
            self.window.table.filesDropped.emit([str(self.path)])
        picker.assert_not_called()
        self.assertEqual(warning.call_count, 2)
        self.assertFalse(self.window.workflow.items)
        self.window.workflow.running = False
        self.window.refresh_status()
        self.assertTrue(self.window.add_btn.isEnabled())
        self.window.table.filesDropped.emit([str(self.path)])
        self.assertEqual(len(self.window.workflow.items), 1)
