import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

import museum as m


class KioskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.data = root / "data"
        self.config = root / "config.json"
        shutil.copytree(m.DATA_DIR, self.data)
        for key, value in [("DATA_DIR", self.data), ("CONFIG_PATH", self.config)]:
            mock = patch.object(m, key, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.win = m.Kiosk(m.load_config(), m.load_people(), 2/3)
        self.win.resize(1280, 720)
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        self.win.go_home()
        self.win._allow_close = True
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def dialog(self, change=True):
        w = self.win
        d = m.PinDialog(w, w._verify, w.scale, w.theme.hc, w.T, change)
        self.addCleanup(d.deleteLater)
        return d

    def enter(self, d, value):
        for digit in value:
            d.press(digit)
        d.press("OK")

    def test_pin_requires_current_confirmation_and_atomic_save(self):
        w = self.win
        original = self.config.read_bytes()
        d = self.dialog()
        for _ in range(5):
            self.enter(d, "9876")
        self.enter(d, "1234")
        self.assertEqual(d.stage, "current")
        self.assertEqual(w._verify("1234"), "locked")
        self.assertEqual(self.config.read_bytes(), original)
        w._locked_until = 0
        self.enter(d, "1234")
        self.enter(d, "1")
        self.assertEqual(d.stage, "new")
        self.enter(d, "5607")
        self.enter(d, "1111")
        self.assertEqual(d.stage, "new")
        d.reject()
        self.assertEqual(self.config.read_bytes(), original)
        d = self.dialog()
        for pin in ("1234", "005678", "005678"):
            self.enter(d, pin)
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(w._verify("1234"), "bad")
        self.assertEqual(w._verify("005678"), "ok")
        self.assertEqual(m.load_config()["pin_hash"], w.cfg["pin_hash"])
        self.assertNotIn("005678", self.config.read_text())
        d = self.dialog()
        self.enter(d, "005678")
        self.enter(d, "4444")
        with patch.object(m, "save_config", side_effect=OSError("read only")):
            self.enter(d, "4444")
        self.assertEqual(d.stage, "current")
        self.assertEqual(w._verify("005678"), "ok")
        d.reject()
        self.config.write_text("{}")
        with self.assertRaises(ValueError):
            m.load_config()
        self.assertEqual(w._verify("1234"), "error")
        self.assertEqual(self.config.read_text(), "{}")

    def test_archive_refresh_and_local_video(self):
        w = self.win
        w.list.setCurrentRow(0)
        initial = len(w.people[0].media)
        folder = self.data / w.people[0].folder
        second = self.data / w.people[1].folder
        m.create_media_folders()
        new_photo = folder / "Фото" / "Мастерская.jpg"
        shutil.copy(w.people[0].portrait, new_photo)
        video = folder / "Видео" / "Экскурсия.MP4"
        shutil.copy(Path(__file__).with_name("playback.mp4"), video)
        shutil.copy(w.people[1].portrait, second / "Фото" / new_photo.name)
        (folder / "Видео" / "notes.txt").write_text("ignore")
        info = json.loads((folder / "info.json").read_text(encoding="utf8"))
        info["captions"]["Видео/" + video.name] = {"en": "A tour", "ru": "Экскурсия"}
        (folder / "info.json").write_text(json.dumps(info), encoding="utf8")
        m.atomic_write(m.revision_path(), b"refresh-1")
        w.check_media_revision()
        w.set_language("en")
        self.assertEqual(w.list.currentRow(), 0)
        self.assertEqual(w.strip.count(), initial + 2)
        self.assertEqual(w.people[0].media[:2], [new_photo, video])
        self.assertNotIn(video, w.people[1].media)
        w.open_overlay(1)
        g = w.overlay.gallery
        self.assertTrue(g.controls.isVisible())
        self.assertEqual(g.caption.text(), "A tour")
        for _ in range(150):
            if not g.view.video_image.isNull():
                break
            QTest.qWait(40)
        self.assertFalse(g.view.video_image.isNull(), g.player.errorString())
        self.assertGreater(g.player.duration(), 0)
        if g.playing():
            g.play_btn.click()
        self.assertFalse(g.playing())
        g.play_btn.click()
        QTest.qWait(80)
        self.assertTrue(g.playing())
        g.next.click()
        self.assertTrue(g.player.source().isEmpty())
        self.assertFalse(g.controls.isVisible())
        g.prev.click()
        self.assertTrue(g.video_active)
        w.overlay.close_btn.click()
        self.assertFalse(w.overlay.isVisible())
        self.assertTrue(g.player.source().isEmpty())
        new_photo.unlink()
        m.atomic_write(m.revision_path(), b"refresh-2")
        w.check_media_revision()
        self.assertEqual(w.strip.count(), initial+1)
        self.assertEqual(w.people[0].media[0], video)
        w.open_overlay(0)
        w.go_home()
        self.assertFalse(g.playing())
        self.assertTrue(g.player.source().isEmpty())

    def test_navigation_pin_entry_and_reduced_motion(self):
        w = self.win
        w.directors_btn.click()
        for row in (2, 1, 4):
            w.list.setCurrentRow(row)
        w.open_portrait()
        self.assertEqual(w.overlay.gallery.photos, [w.people[4].portrait])
        w.overlay.close_btn.click()
        w.btn_contrast.click()
        w.open_overlay(0)
        self.assertFalse(w.transition.isVisible())
        w.overlay.close_btn.click()
        def cancel_current():
            d = self.app.activeModalWidget()
            self.assertEqual(d.stage, "current")
            d.reject()
        QTimer.singleShot(0, cancel_current)
        w.pin_btn.click()
        self.assertFalse(w._allow_close)
        self.assertFalse(w.dim.isVisible())
        w.go_home()
        self.assertEqual(w.stack.currentIndex(), 0)


if __name__ == "__main__":
    unittest.main()
