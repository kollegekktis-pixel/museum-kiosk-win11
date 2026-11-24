# -*- coding: utf-8 -*-
"""
Музей колледжа - информационный киоск (офлайн, Windows 11, сенсорный экран).

Структура рядом с программой:
    museum.exe (или museum.py)
    config.json              <- создаётся автоматически (пароль, язык по умолчанию и т.д.)
    data/
        Иванов Иван Иванович/
            info.json
            portrait.jpg     <- портрет директора (в углу и на иконке в списке)
            1.jpg, 2.jpg ... <- остальные фото = архивные, показываются внизу

info.json (языки необязательны; если перевода нет, берётся русский):
    {
      "name":        {"ru": "Иванов Иван Иванович", "kk": "Иванов Иван Иванұлы", "en": "Ivan Ivanov"},
      "years":       {"ru": "1965–1978", "kk": "1965–1978", "en": "1965–1978"},
      "description": {"ru": "Текст...", "kk": "Мәтін...", "en": "Text..."},
      "captions":    {"1.jpg": {"ru": "Подпись", "kk": "Жазу", "en": "Caption"}}
    }
Можно писать и просто строками: "years": "1965–1978".

Смена пароля (только цифры):   museum.exe --setpin 5678
Пароль по умолчанию:           1234
Выход:  кнопка "Выход" внизу слева (или Ctrl+Shift+Q) -> пароль.
"""
import os
import sys
import re
import json
import posixpath
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile
import time
import html
import hashlib
import secrets
import tempfile
import subprocess
from pathlib import Path
from types import SimpleNamespace
from collections import OrderedDict
from contextlib import contextmanager

from PyQt6.QtCore import (Qt, QTimer, QEvent, QSize, QPoint, QRect, QSaveFile, QIODevice, QRectF,
                          QEasingCurve, QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import (QPixmap, QImage, QImageReader, QPainter, QColor, QFont, QKeySequence, QShortcut,
                         QPainterPath, QLinearGradient, QBrush, QPen, QFontMetrics)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QStackedWidget, QScrollArea,
    QScroller, QComboBox, QFileDialog, QMessageBox, QTextBrowser, QDialog, QFrame, QAbstractItemView, QStyledItemDelegate, QStyle,
)

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PORTRAIT_NAMES = {"portrait", "портрет", "director", "директор"}

# флаги выравнивания/переноса одним числом (чтобы не смешивать разные enum)
A_LEFT_TOP = Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignTop.value
A_WRAP = A_LEFT_TOP | Qt.TextFlag.TextWordWrap.value
A_LEFT_VC = Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignVCenter.value
A_LEFT_BOTTOM = Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignBottom.value

# ----------------------------------------------------------------- языки
LANGS = ("ru", "kk", "en")

I18N = {
    "ru": {
        "title": "Музей колледжа",
        "subtitle": "РУКОВОДИТЕЛИ КОЛЛЕДЖА",
        "welcome": "Выберите человека в списке слева\nи узнайте его историю",
        "no_data": "Папка data пуста или не найдена.\nДобавьте данные рядом с программой.",
        "history": "ИСТОРИЯ",
        "archive": "АРХИВНЫЕ ФОТОГРАФИИ",
        "years": "Годы руководства",
        "exit": "Выход",
        "pin_title": "Введите пароль",
        "pin_bad": "Неверный пароль",
        "pin_locked": "Слишком много попыток, подождите минуту",
        "cancel": "Отмена",
        "contrast": "Контраст",
        "narrator": "Диктор",
        "read": "Прочитать вслух",
        "stop": "Остановить",
    },
    "kk": {
        "title": "Колледж мұражайы",
        "subtitle": "КОЛЛЕДЖ БАСШЫЛАРЫ",
        "welcome": "Сол жақтағы тізімнен адамды таңдаңыз\nжәне оның тарихын біліңіз",
        "no_data": "data қалтасы бос немесе табылмады.\nДеректерді бағдарламаның жанына қосыңыз.",
        "history": "ТАРИХ",
        "archive": "МҰРАҒАТТЫҚ ФОТОЛАР",
        "years": "Басшылық жылдары",
        "exit": "Шығу",
        "pin_title": "Құпиясөзді енгізіңіз",
        "pin_bad": "Құпиясөз дұрыс емес",
        "pin_locked": "Тым көп әрекет, бір минут күтіңіз",
        "cancel": "Бас тарту",
        "contrast": "Контраст",
        "narrator": "Диктор",
        "read": "Дауыстап оқу",
        "stop": "Тоқтату",
    },
    "en": {
        "title": "College Museum",
        "subtitle": "COLLEGE LEADERS",
        "welcome": "Select a person from the list\nto learn their story",
        "no_data": "The data folder is empty or not found.\nAdd data next to the program.",
        "history": "HISTORY",
        "archive": "ARCHIVE PHOTOS",
        "years": "Years in office",
        "exit": "Exit",
        "pin_title": "Enter password",
        "pin_bad": "Incorrect password",
        "pin_locked": "Too many attempts, please wait a minute",
        "cancel": "Cancel",
        "contrast": "Contrast",
        "narrator": "Narrator",
        "read": "Read aloud",
        "stop": "Stop",
    },
}


def tr(value, lang) -> str:
    """Строка или словарь {ru,kk,en} -> строка на нужном языке (запасной вариант - русский)."""
    if isinstance(value, dict):
        v = value.get(lang) or value.get("ru")
        if not v:
            v = next((x for x in value.values() if x), "")
        return str(v)
    return "" if value is None else str(value)


class Theme:
    """Настройки доступности: высокий контраст и множитель размера текста."""

    def __init__(self):
        self.hc = False
        self.mult = 1.0


# ----------------------------------------------------------------- пути, конфиг
def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


DATA_DIR = app_dir() / "data"
CONFIG_PATH = app_dir() / "config.json"


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}
    changed = False
    if "salt" not in cfg or "pin_hash" not in cfg:
        cfg["salt"] = secrets.token_hex(8)
        cfg["pin_hash"] = hash_pin("1234", cfg["salt"])
        changed = True
    for key, val in (("hide_cursor", False), ("idle_reset_seconds", 120), ("language", "ru")):
        if key not in cfg:
            cfg[key] = val
            changed = True
    if changed:
        try:
            save_config(cfg)
        except Exception:
            pass
    return cfg


# ----------------------------------------------------------------- данные
def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


class Person:
    def __init__(self, folder, info, photos, portrait, sort_key):
        self.folder = folder
        self.info = info
        self.photos = photos      # архивные фото
        self.portrait = portrait  # портрет (или None)
        self.sort_key = sort_key

    def name(self, lang):
        return tr(self.info.get("name"), lang) or self.folder

    def years(self, lang):
        return tr(self.info.get("years"), lang)

    def period_text(self, lang):
        years = self.years(lang)
        label = tr(self.info.get("period_label"), lang) or I18N[lang]["years"]
        return f"{label}: {years}" if years else ""

    def description(self, lang):
        return tr(self.info.get("description"), lang)

    def captions(self, lang):
        caps = self.info.get("captions") or {}
        return {k: tr(v, lang) for k, v in caps.items()}


def load_people():
    people = []
    if not DATA_DIR.is_dir():
        return people
    for d in DATA_DIR.iterdir():
        if not d.is_dir():
            continue
        info = {}
        jp, tp = d / "info.json", d / "info.txt"
        if jp.exists():
            try:
                info = json.loads(jp.read_text(encoding="utf-8-sig"))
            except Exception:
                info = {}
        elif tp.exists():
            try:
                lines = tp.read_text(encoding="utf-8-sig").splitlines()
                info = {"years": lines[0].strip() if lines else "",
                        "description": "\n".join(lines[1:]).strip()}
            except Exception:
                info = {}
        photos = sorted((p for p in d.iterdir() if p.suffix.lower() in IMG_EXT),
                        key=lambda p: natural_key(p.name))
        portrait = None
        wanted = str(info.get("portrait", "")).lower()
        for p in photos:
            if (wanted and p.name.lower() == wanted) or (not wanted and p.stem.lower() in PORTRAIT_NAMES):
                portrait = p
                break
        if portrait is not None:
            photos = [p for p in photos if p != portrait]
        m = re.search(r"\d{4}", tr(info.get("years"), "ru"))
        order = info.get("order")
        sort_key = (order if isinstance(order, (int, float)) else (int(m.group()) if m else 9999),
                    natural_key(d.name))
        people.append(Person(d.name, info, photos, portrait, sort_key))
    people.sort(key=lambda p: p.sort_key)
    return people


# ----------------------------------------------------------------- картинки
MAX_SIDE = 2200


def load_pixmap(path, max_side=None) -> QPixmap:
    max_side = max_side or MAX_SIDE
    r = QImageReader(str(path))
    r.setAutoTransform(True)
    size = r.size()
    if size.isValid() and max(size.width(), size.height()) > max_side:
        size.scale(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio)
        r.setScaledSize(size)
    img = r.read()
    return QPixmap.fromImage(img) if not img.isNull() else QPixmap()


def cover_pixmap(pm: QPixmap, w: int, h: int, anchor_y=0.2) -> QPixmap:
    """Заполняет прямоугольник w x h фото целиком (лишнее обрезается), лицо обычно сверху."""
    out = QPixmap(max(1, w), max(1, h))
    out.fill(Qt.GlobalColor.transparent)
    if pm.isNull() or w <= 0 or h <= 0:
        return out
    sc = pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation)
    x = (sc.width() - w) // 2
    y = int((sc.height() - h) * anchor_y)
    p = QPainter(out)
    p.drawPixmap(0, 0, sc, x, y, w, h)
    p.end()
    return out


class ThumbCache:
    """Миниатюры (быстро: фото сразу декодируется в уменьшенном размере)."""

    def __init__(self):
        self.d = {}

    def get(self, path, w, h, anchor=0.3) -> QPixmap:
        key = (str(path), w, h, anchor)
        pm = self.d.get(key)
        if pm is None:
            r = QImageReader(str(path))
            r.setAutoTransform(True)
            size = r.size()
            if size.isValid() and size.width() > 0:
                target = max(w, h) * 2
                if max(size.width(), size.height()) > target:
                    size.scale(target, target, Qt.AspectRatioMode.KeepAspectRatio)
                    r.setScaledSize(size)
            img = r.read()
            pm = cover_pixmap(QPixmap.fromImage(img), w, h, anchor) if not img.isNull() else QPixmap(w, h)
            self.d[key] = pm
        return pm


class PixCache:
    def __init__(self, n=8):
        self.d = OrderedDict()
        self.n = n

    def get(self, path) -> QPixmap:
        k = str(path)
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        pm = load_pixmap(path)
        self.d[k] = pm
        while len(self.d) > self.n:
            self.d.popitem(last=False)
        return pm


# ----------------------------------------------------------------- блокировка клавиш (Windows)
class KeyboardLock:
    """Блокирует Alt+Tab, Alt+Esc, Alt+F4, Win, Ctrl+Esc, Ctrl+Shift+Esc.
    Ctrl+Alt+Del программно заблокировать нельзя - закройте его политикой Windows."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        u = self.user32
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        u.SetWindowsHookExW.restype = wintypes.HHOOK
        u.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        u.CallNextHookEx.restype = ctypes.c_ssize_t
        u.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        def proc(n_code, w_param, l_param):
            if n_code == 0:
                k = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = k.vkCode
                alt = bool(k.flags & 0x20)
                ctrl = bool(u.GetAsyncKeyState(0x11) & 0x8000)
                if (vk in (0x5B, 0x5C, 0x5D)                 # Win, Win, Menu
                        or (alt and vk in (0x09, 0x1B, 0x73))  # Alt+Tab / Alt+Esc / Alt+F4
                        or (ctrl and vk == 0x1B)):             # Ctrl+Esc, Ctrl+Shift+Esc
                    return 1
            return u.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = HOOKPROC(proc)  # держим ссылку, иначе сборщик мусора уронит программу
        self._hook = u.SetWindowsHookExW(13, self._proc, kernel32.GetModuleHandleW(None), 0)

    def remove(self):
        if self._hook:
            self.user32.UnhookWindowsHookEx(self._hook)
            self._hook = None


def install_keyboard_lock():
    if sys.platform != "win32":
        return None
    try:
        return KeyboardLock()
    except Exception:
        return None


# ----------------------------------------------------------------- экранный диктор (офлайн, голоса Windows)
class Speaker:
    """Читает текст голосом Windows (System.Speech через PowerShell). Интернет не нужен.
    Голос подбирается по языку; для казахского, если голоса нет, читает русский."""

    SCRIPT = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$all = $s.GetInstalledVoices() | Where-Object { $_.Enabled };"
        "$v = $all | Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq '@LANG@' } | Select-Object -First 1;"
        "if (-not $v -and '@LANG@' -eq 'kk') { $v = $all | Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'ru' } | Select-Object -First 1 };"
        "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) };"
        "$s.Rate = -1;"
        "$s.Speak([System.IO.File]::ReadAllText('@PATH@', [System.Text.Encoding]::UTF8));"
    )

    def __init__(self):
        self.proc = None
        self.tmp = None

    def available(self):
        return sys.platform == "win32"

    def is_speaking(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None
        if self.tmp:
            try:
                os.remove(self.tmp)
            except Exception:
                pass
            self.tmp = None

    def speak(self, text, lang):
        self.stop()
        if not self.available() or not text.strip():
            return
        try:
            fd, path = tempfile.mkstemp(suffix=".txt")
            os.close(fd)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self.tmp = path
            script = self.SCRIPT.replace("@LANG@", lang).replace("@PATH@", path.replace("'", "''"))
            self.proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-Command", script],
                creationflags=0x08000000,  # без окна консоли
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            self.proc = None


# ----------------------------------------------------------------- виджеты
class NavigationTransition(QWidget):
    """Плавно убирает предыдущий кадр. Касания сразу получает новый экран."""

    def __init__(self, kiosk):
        super().__init__(kiosk)
        self.kiosk = kiosk
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        self.frame = QPixmap()
        self.offset = QPoint()
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(220)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.valueChanged.connect(lambda _: self.update())
        self.animation.finished.connect(self.clear)
        hints = QApplication.styleHints()
        self.accessibility = hints.accessibility() if hasattr(hints, "accessibility") else None
        if hasattr(self.accessibility, "motionPreferenceChanged"):
            self.accessibility.motionPreferenceChanged.connect(lambda _: self.clear())

    def clear(self):
        self.animation.stop()
        self.hide()
        self.frame = QPixmap()

    def motion_enabled(self):
        if self.kiosk.theme.hc:
            return False
        if hasattr(self.accessibility, "motionPreference"):
            preference = self.accessibility.motionPreference()
            return preference != type(preference).ReducedMotion
        return bool(self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate))

    @contextmanager
    def switch(self, surface, dx=0, dy=0):
        if not surface.isVisible() or not self.motion_enabled():
            self.clear()
            yield
            return
        bounds = QRect(surface.mapTo(self.kiosk, QPoint()), surface.size())
        # Снимок включает уже видимую часть прерванного перехода и фон страницы.
        frame = self.kiosk.grab(bounds)
        self.clear()
        yield
        self.setGeometry(bounds)
        self.frame = frame
        self.offset = QPoint(round(dx * self.kiosk.scale), round(dy * self.kiosk.scale))
        self.raise_()
        self.show()
        self.animation.start()

    def paintEvent(self, event):
        progress = self.animation.currentValue()
        painter = QPainter(self)
        painter.setOpacity(1.0 - progress)
        painter.drawPixmap(self.offset * progress, self.frame)


class PhotoView(QWidget):
    tapped = pyqtSignal()
    swiped = pyqtSignal(int)  # -1 назад, +1 вперёд

    def __init__(self, radius=0):
        super().__init__()
        self.radius = radius
        self._pm = None
        self._scaled = None
        self._press = None
        self.setMinimumSize(300, 200)

    def set_pixmap(self, pm):
        self._pm = pm
        self._rescale()
        self.update()

    def _rescale(self):
        if self._pm is not None and not self._pm.isNull() and self.width() > 0:
            self._scaled = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        else:
            self._scaled = None

    def resizeEvent(self, e):
        self._rescale()
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor("#08172c"))
        if self._scaled is not None:
            x = (self.width() - self._scaled.width()) // 2
            y = (self.height() - self._scaled.height()) // 2
            p.drawPixmap(x, y, self._scaled)

    def mousePressEvent(self, e):
        self._press = e.position().toPoint()

    def mouseReleaseEvent(self, e):
        if self._press is None:
            return
        d = e.position().toPoint() - self._press
        self._press = None
        if abs(d.x()) > 60 and abs(d.x()) > abs(d.y()):
            self.swiped.emit(1 if d.x() < 0 else -1)
        elif abs(d.x()) < 20 and abs(d.y()) < 20:
            self.tapped.emit()


class GalleryPanel(QWidget):
    tapped = pyqtSignal()

    def __init__(self, cache: PixCache, scale: float, transition, radius=22):
        super().__init__()
        self.cache = cache
        self.transition = transition
        self.photos = []
        self.captions = {}
        self.index = 0

        self.view = PhotoView(int(radius * scale))
        self.view.swiped.connect(self.step)
        self.view.tapped.connect(self.tapped)

        btn = int(90 * scale)
        self.prev = QPushButton("‹")
        self.next = QPushButton("›")
        for b in (self.prev, self.next):
            b.setObjectName("nav")
            b.setFixedSize(btn, btn)
        self.prev.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))

        self.caption = QLabel()
        self.caption.setObjectName("caption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        self.counter = QLabel()
        self.counter.setObjectName("counter")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mid = QVBoxLayout()
        mid.setSpacing(int(6 * scale))
        mid.addWidget(self.caption)
        mid.addWidget(self.counter, 0, Qt.AlignmentFlag.AlignHCenter)
        bar = QHBoxLayout()
        bar.addWidget(self.prev)
        bar.addLayout(mid, 1)
        bar.addWidget(self.next)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(int(14 * scale))
        lay.addWidget(self.view, 1)
        lay.addLayout(bar)

    def set_photos(self, photos, captions, index=0):
        self.photos = list(photos)
        self.captions = captions or {}
        self.show_index(index)

    def show_index(self, i):
        if not self.photos:
            self.view.set_pixmap(None)
            self.caption.setText("")
            self.counter.setText("")
            self.prev.setVisible(False)
            self.next.setVisible(False)
            return
        self.index = i % len(self.photos)
        path = self.photos[self.index]
        self.view.set_pixmap(self.cache.get(path))
        self.caption.setText(str(self.captions.get(path.name, "")))
        self.counter.setText(f"{self.index + 1} / {len(self.photos)}")
        multi = len(self.photos) > 1
        self.prev.setVisible(multi)
        self.next.setVisible(multi)
        self.counter.setVisible(multi)

    def step(self, d):
        if len(self.photos) > 1:
            with self.transition.switch(self.view, dx=-48 * d):
                self.show_index(self.index + d)


class Overlay(QWidget):
    """Фото на весь экран поверх основного окна."""
    closed = pyqtSignal()

    def __init__(self, parent, cache, scale):
        super().__init__(parent)
        self.setObjectName("overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.transition = parent.transition
        self.gallery = GalleryPanel(cache, scale, self.transition, radius=0)
        self.gallery.tapped.connect(self._close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(int(20 * scale), int(20 * scale), int(20 * scale), int(20 * scale))
        lay.addWidget(self.gallery)
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setObjectName("nav")
        self.close_btn.setFixedSize(int(90 * scale), int(90 * scale))
        self.close_btn.clicked.connect(self._close)
        self.hide()

    def _close(self):
        with self.transition.switch(self):
            self.hide()
        self.closed.emit()

    def resizeEvent(self, e):
        self.close_btn.move(self.width() - self.close_btn.width() - 20, 20)
        self.close_btn.raise_()
        super().resizeEvent(e)


class PortraitView(QWidget):
    """Портрет директора в углу страницы. Касание - открыть на весь экран."""
    tapped = pyqtSignal()

    def __init__(self, scale, theme):
        super().__init__()
        self.s = scale
        self.theme = theme
        self.pm = None
        self.initials = "?"
        self._cache = None
        self._press = False

    def set_person(self, pm, name):
        self.pm = pm
        parts = name.split()
        self.initials = ((parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()) if parts else "?"
        self._cache = None
        self.update()

    def has_photo(self):
        return self.pm is not None and not self.pm.isNull()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def paintEvent(self, e):
        s = self.s
        hc = self.theme.hc
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        path = QPainterPath()
        path.addRoundedRect(r, 28 * s, 28 * s)
        if self.has_photo():
            if self._cache is None or self._cache.size() != self.size():
                self._cache = cover_pixmap(self.pm, self.width(), self.height(), 0.15)
            p.setClipPath(path)
            p.drawPixmap(0, 0, self._cache)
            p.setClipping(False)
        else:
            if hc:
                p.fillPath(path, QColor("#000000"))
            else:
                g = QLinearGradient(r.topLeft(), r.bottomRight())
                g.setColorAt(0, QColor("#102e65"))
                g.setColorAt(1, QColor("#0e72b8"))
                p.fillPath(path, QBrush(g))
            f = QFont("Segoe UI")
            f.setPixelSize(int(110 * s))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#ffe600") if hc else QColor("#d3aa58"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.initials)
        p.setPen(QPen(QColor("#ffe600") if hc else QColor("#d3aa58"), (6 if hc else 3) * s))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def mousePressEvent(self, e):
        self._press = True

    def mouseReleaseEvent(self, e):
        if self._press and self.has_photo():
            self.tapped.emit()
        self._press = False


class ThumbDelegate(QStyledItemDelegate):
    """Миниатюра архивного фото со скруглением и подписью."""

    def __init__(self, scale, thumbs, size, captions_getter, theme, parent=None):
        super().__init__(parent)
        self.s = scale
        self.thumbs = thumbs
        self.size_ = size  # (w, h)
        self.captions_getter = captions_getter
        self.theme = theme

    def sizeHint(self, option, index):
        return QSize(self.size_[0] + int(18 * self.s), self.size_[1] + int(8 * self.s))

    def paint(self, p, option, index):
        s = self.s
        hc = self.theme.hc
        path = index.data(Qt.ItemDataRole.UserRole)
        w, h = self.size_
        r = QRectF(option.rect.left() + 9 * s, option.rect.top() + 4 * s, w, h)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(r, 18 * s, 18 * s)
        p.setClipPath(clip)
        p.drawPixmap(int(r.left()), int(r.top()), self.thumbs.get(path, w, h))
        cap = self.captions_getter().get(path.name, "")
        if cap:
            f = QFont("Segoe UI")
            f.setPixelSize(int(18 * s * self.theme.mult))
            fm = QFontMetrics(f)
            bh = fm.lineSpacing() + 36 * s
            band = QRectF(r.left(), r.bottom() - bh, w, bh)
            g = QLinearGradient(band.topLeft(), band.bottomLeft())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 235 if hc else 200))
            p.fillRect(band, QBrush(g))
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(band.adjusted(14 * s, 0, -14 * s, -8 * s), A_LEFT_BOTTOM,
                       fm.elidedText(str(cap), Qt.TextElideMode.ElideRight, int(w - 28 * s)))
        p.setClipping(False)
        p.setPen(QPen(QColor("#ffffff") if hc else QColor("#b09258"), (3 if hc else 1.5)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(clip)
        p.restore()


class PersonDelegate(QStyledItemDelegate):
    """Карточка человека в списке: фото (или инициалы), имя, годы."""

    def __init__(self, scale, thumbs, theme, parent=None):
        super().__init__(parent)
        self.s = scale
        self.thumbs = thumbs
        self.theme = theme

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), int(122 * self.s * (1 + 0.5 * (self.theme.mult - 1))))

    def paint(self, p, option, index):
        s = self.s
        th = self.theme
        hc, m = th.hc, th.mult
        name, years, portrait = index.data(Qt.ItemDataRole.UserRole)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        r = QRectF(option.rect).adjusted(0, 5 * s, 0, -5 * s)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QPainterPath()
        card.addRoundedRect(r, 20 * s, 20 * s)
        if sel:
            if hc:
                p.fillPath(card, QColor("#ffe600"))
            else:
                g = QLinearGradient(r.topLeft(), r.bottomRight())
                g.setColorAt(0, QColor("#ffedc3"))
                g.setColorAt(1, QColor("#e7ba65"))
                p.fillPath(card, QBrush(g))
        else:
            if hc:
                p.fillPath(card, QColor("#000000"))
                p.setPen(QPen(QColor("#ffffff"), 3))
            else:
                p.fillPath(card, QColor(255, 255, 255, 20))
                p.setPen(QPen(QColor(183, 218, 255, 95), 1))
            p.drawPath(card)

        # --- аватар: фото директора или инициалы
        d = 84 * s
        circle = QRectF(r.left() + 16 * s, r.center().y() - d / 2, d, d)
        dark = QColor("#000000") if hc else QColor("#0f172a")
        ring = QColor("#ffe600") if hc else QColor("#e7ba65")
        if portrait:
            pm = self.thumbs.get(portrait, int(d), int(d), 0.12)
            clip = QPainterPath()
            clip.addEllipse(circle)
            p.setClipPath(clip)
            p.drawPixmap(int(circle.left()), int(circle.top()), pm)
            p.setClipping(False)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(dark if sel else ring, 3.5 * s))
            p.drawEllipse(circle)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dark if sel else ring)
            p.drawEllipse(circle)
            parts = name.split()
            ini = ((parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()) if parts else "?"
            f = QFont("Segoe UI")
            f.setPixelSize(int(28 * s))
            f.setBold(True)
            p.setFont(f)
            p.setPen(ring if sel else dark)
            p.drawText(circle, Qt.AlignmentFlag.AlignCenter, ini)

        # --- текст
        x = circle.right() + 16 * s
        w = r.right() - x - 14 * s
        px = int(25 * s * m)
        minpx = int(17 * s)
        nf = QFont("Segoe UI")
        nf.setBold(True)
        while True:
            nf.setPixelSize(px)
            fm = QFontMetrics(nf)
            br = fm.boundingRect(0, 0, int(w), 10000, A_WRAP, name)
            if br.height() <= fm.lineSpacing() * 2 + 2 or px <= minpx:
                break
            px -= 1
        name_h = br.height()
        yf = QFont("Segoe UI")
        yf.setPixelSize(int(21 * s * m))
        yfm = QFontMetrics(yf)
        years_h = yfm.lineSpacing() if years else 0
        gap = 4 * s if years else 0
        y0 = r.center().y() - (name_h + gap + years_h) / 2
        p.setFont(nf)
        p.setPen(QColor("#000000") if (hc and sel) else (dark if sel else QColor("#f8fafc")))
        p.drawText(QRectF(x, y0, w, name_h), A_WRAP, name)
        if years:
            p.setFont(yf)
            if sel:
                p.setPen(QColor("#000000") if hc else QColor(15, 23, 42, 210))
            else:
                p.setPen(QColor("#ffe600") if hc else QColor("#ffda90"))
            p.drawText(QRectF(x, y0 + name_h + gap, w, years_h), A_LEFT_TOP,
                       yfm.elidedText(years, Qt.TextElideMode.ElideRight, int(w)))
        p.restore()


class PinDialog(QDialog):
    def __init__(self, parent, verify, scale, hc, T):
        super().__init__(parent)
        self.verify = verify
        self.scale = scale
        self.hc = hc
        self.T = T
        self.pin = ""
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setObjectName("pin")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        title = QLabel(T("pin_title"))
        title.setObjectName("pinTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display = QLabel(" ")
        self.display.setObjectName("pinDisplay")
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel(" ")
        self.status.setObjectName("pinStatus")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)

        grid = QGridLayout()
        grid.setSpacing(int(10 * scale))
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]
        for i, k in enumerate(keys):
            b = QPushButton(k)
            b.setObjectName("key")
            b.setFixedSize(int(110 * scale), int(95 * scale))
            b.clicked.connect(lambda _, kk=k: self.press(kk))
            grid.addWidget(b, i // 3, i % 3)
        cancel = QPushButton(T("cancel"))
        cancel.setObjectName("keyCancel")
        cancel.setFixedHeight(int(80 * scale))
        cancel.clicked.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(int(30 * scale), int(30 * scale), int(30 * scale), int(30 * scale))
        lay.addWidget(title)
        lay.addWidget(self.display)
        lay.addWidget(self.status)
        lay.addLayout(grid)
        lay.addWidget(cancel)

        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.setInterval(30000)  # само закрывается через 30 сек бездействия
        self._auto.timeout.connect(self.reject)
        self._auto.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#000000") if self.hc else QColor("#0c2a53"))
        p.setPen(QPen(QColor("#ffe600") if self.hc else QColor("#e7ba65"), 4 if self.hc else 3))
        r = 28 * self.scale
        p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), r, r)

    def press(self, k):
        self._auto.start()
        if k == "⌫":
            self.pin = self.pin[:-1]
        elif k == "OK":
            self.submit()
            return
        elif len(self.pin) < 12:
            self.pin += k
        self.display.setText("●" * len(self.pin) if self.pin else " ")

    def submit(self):
        res = self.verify(self.pin)
        if res == "ok":
            self.accept()
            return
        self.pin = ""
        self.display.setText(" ")
        self.status.setText(self.T("pin_locked") if res == "locked" else self.T("pin_bad"))

    def keyPressEvent(self, e):
        t = e.text()
        if t.isdigit():
            self.press(t)
        elif e.key() == Qt.Key.Key_Backspace:
            self.press("⌫")
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.press("OK")
        elif e.key() == Qt.Key.Key_Escape:
            self.reject()


# ----------------------------------------------------------------- главное окно
class Kiosk(QWidget):
    def __init__(self, cfg, people, scale):
        super().__init__()
        self.cfg = cfg
        college_file = DATA_DIR / "college.json"
        self.college = json.loads(college_file.read_text(encoding="utf-8")) if college_file.is_file() else {}
        self.people = people
        self.scale = scale
        self.cache = PixCache()
        self.thumbs = ThumbCache()
        self.theme = Theme()
        self.speaker = Speaker()
        self.narrator = False
        self.lang = cfg.get("language") if cfg.get("language") in LANGS else "ru"
        self.default_lang = self.lang
        self._caps = {}
        self.lock = None
        self._allow_close = False
        self._pin_open = False
        self._fails = 0
        self._locked_until = 0.0

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Museum")
        if cfg.get("hide_cursor"):
            self.setCursor(Qt.CursorShape.BlankCursor)
        self.transition = NavigationTransition(self)
        self._build_ui()
        self.apply_theme()
        self.set_language(self.lang)

        QShortcut(QKeySequence("Ctrl+Shift+Q"), self, activated=self.ask_password)

        self.keep_top = QTimer(self)
        self.keep_top.setInterval(3000)
        self.keep_top.timeout.connect(self._keep_top)
        self.keep_top.start()

        self.sp_timer = QTimer(self)
        self.sp_timer.setInterval(400)
        self.sp_timer.timeout.connect(self.update_read_btn)
        self.sp_timer.start()

        secs = int(cfg.get("idle_reset_seconds", 0) or 0)
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        if secs > 0:
            self.idle.setInterval(secs * 1000)
            self.idle.timeout.connect(self.go_home)
            self.idle.start()

    # --- тексты
    def T(self, key):
        return I18N[self.lang].get(key) or I18N["ru"][key]

    def title_for(self):
        t = self.cfg.get("title")
        if isinstance(t, dict):
            return tr(t, self.lang) or self.T("title")
        if isinstance(t, str) and t.strip() and t.strip() != I18N["ru"]["title"]:
            return t  # своё название колледжа для всех языков
        return self.T("title")

    # --- UI
    def _tool_button(self, text, checkable=False):
        b = QPushButton(text)
        b.setObjectName("tool")
        b.setCheckable(checkable)
        b.setMinimumHeight(int(64 * self.scale))
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    def _build_ui(self):
        s = self.scale
        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- левая панель
        left = QWidget()
        left.setObjectName("left")
        left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left.setFixedWidth(int(540 * s))
        lv = QVBoxLayout(left)
        lv.setContentsMargins(int(26 * s), int(32 * s), int(26 * s), int(26 * s))
        lv.setSpacing(int(10 * s))

        head = QHBoxLayout()
        head.setSpacing(int(16 * s))
        badge = QLabel()
        badge.setObjectName("badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(int(80 * s), int(80 * s))
        emblem = QPixmap(str(DATA_DIR / "logo.png"))
        if not emblem.isNull():
            badge.setPixmap(emblem.scaled(badge.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        else:
            badge.setText("ККТиС")
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.title_lbl = QLabel()
        self.title_lbl.setObjectName("title")
        self.title_lbl.setWordWrap(True)
        self.sub_lbl = QLabel()
        self.sub_lbl.setObjectName("subtitle")
        self.sub_lbl.setWordWrap(True)
        tcol.addWidget(self.title_lbl)
        tcol.addWidget(self.sub_lbl)
        head.addWidget(badge)
        head.addLayout(tcol, 1)
        lv.addLayout(head)
        lv.addSpacing(int(14 * s))

        self.home_btn = self._tool_button("", True)
        self.home_btn.clicked.connect(self.open_history)
        lv.addWidget(self.home_btn)
        self.list = QListWidget()
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setSpacing(0)
        self.list.setItemDelegate(PersonDelegate(s, self.thumbs, self.theme, self.list))
        QScroller.grabGesture(self.list.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        self.list.currentItemChanged.connect(self._on_item)
        lv.addWidget(self.list, 1)

        self.exit_btn = QPushButton()
        self.exit_btn.setObjectName("exitBtn")
        self.exit_btn.setMinimumHeight(int(68 * s))
        self.exit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.exit_btn.clicked.connect(self.ask_password)
        lv.addWidget(self.exit_btn)

        # ---- правая часть: панель инструментов + страницы
        rightw = QWidget()
        rv = QVBoxLayout(rightw)
        rv.setContentsMargins(int(40 * s), int(20 * s), int(40 * s), 0)
        rv.setSpacing(0)

        bar = QHBoxLayout()
        bar.setSpacing(int(10 * s))
        self.lang_btns = {}
        for code, label in (("ru", "РУС"), ("kk", "ҚАЗ"), ("en", "ENG")):
            b = self._tool_button(label, True)
            b.setMinimumWidth(int(100 * s))
            b.clicked.connect(lambda _, c=code: self.select_language(c))
            self.lang_btns[code] = b
            bar.addWidget(b)
        bar.addStretch(1)
        self.btn_minus = self._tool_button("A−")
        self.btn_plus = self._tool_button("A+")
        for b in (self.btn_minus, self.btn_plus):
            b.setMinimumWidth(int(84 * s))
        self.btn_minus.clicked.connect(lambda: self.change_text_size(-0.2))
        self.btn_plus.clicked.connect(lambda: self.change_text_size(0.2))
        self.btn_contrast = self._tool_button("", True)
        self.btn_contrast.toggled.connect(self.on_contrast)
        self.btn_narr = self._tool_button("", True)
        self.btn_narr.toggled.connect(self.on_narrator)
        bar.addWidget(self.btn_minus)
        bar.addWidget(self.btn_plus)
        bar.addWidget(self.btn_contrast)
        bar.addWidget(self.btn_narr)
        if not self.speaker.available():
            self.btn_narr.hide()
        rv.addLayout(bar)

        self.stack = QStackedWidget()
        rv.addWidget(self.stack, 1)

        welcome = QWidget()
        wl = QVBoxLayout(welcome)
        wl.setContentsMargins(0, int(22*s), 0, int(22*s))
        wl.setSpacing(int(18*s))
        self.story_period = QLabel("1956 — 2026")
        self.story_period.setObjectName("era")
        wl.addWidget(self.story_period)
        self.story_heading = QLabel()
        self.story_heading.setObjectName("storyHeading")
        self.story_heading.setWordWrap(True)
        wl.addWidget(self.story_heading)
        self.history_reader = QTextBrowser()
        self.history_reader.setObjectName("collegeStory")
        self.history_reader.setOpenExternalLinks(False)
        self.history_reader.setFrameShape(QFrame.Shape.NoFrame)
        QScroller.grabGesture(self.history_reader.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        wl.addWidget(self.history_reader, 1)
        actions = QHBoxLayout()
        self.history_read = self._tool_button("")
        self.history_read.clicked.connect(self.toggle_read)
        self.history_read.setVisible(self.speaker.available())
        actions.addWidget(self.history_read)
        actions.addStretch()
        self.directors_btn = self._tool_button("")
        self.directors_btn.setObjectName("primary")
        self.directors_btn.clicked.connect(lambda: self.list.setCurrentRow(0))
        self.directors_btn.setEnabled(bool(self.people))
        actions.addWidget(self.directors_btn)
        wl.addLayout(actions)
        self.stack.addWidget(welcome)

        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, int(14 * s), 0, int(28 * s))
        pv.setSpacing(int(14 * s))

        top = QHBoxLayout()
        top.setSpacing(int(32 * s))
        info_col = QVBoxLayout()
        info_col.setSpacing(int(12 * s))
        self.name_lbl = QLabel()
        self.name_lbl.setObjectName("name")
        self.name_lbl.setWordWrap(True)
        pill_row = QHBoxLayout()
        self.years_lbl = QLabel()
        self.years_lbl.setObjectName("years")
        self.years_lbl.setWordWrap(True)
        pill_row.addWidget(self.years_lbl)
        pill_row.addStretch(1)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(int(30 * s), int(22 * s), int(16 * s), int(24 * s))
        cl.setSpacing(int(10 * s))
        card_head_row = QHBoxLayout()
        self.card_head = QLabel()
        self.card_head.setObjectName("cardHead")
        self.read_btn = self._tool_button("")
        self.read_btn.setMinimumHeight(int(52 * s))
        self.read_btn.clicked.connect(self.toggle_read)
        card_head_row.addWidget(self.card_head)
        card_head_row.addStretch(1)
        card_head_row.addWidget(self.read_btn)
        if not self.speaker.available():
            self.read_btn.hide()
        self.desc = QLabel()
        self.desc.setObjectName("desc")
        self.desc.setTextFormat(Qt.TextFormat.RichText)
        self.desc.setWordWrap(True)
        self.desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidget(self.desc)
        QScroller.grabGesture(sa.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        cl.addLayout(card_head_row)
        cl.addWidget(sa, 1)

        info_col.addWidget(self.name_lbl)
        info_col.addLayout(pill_row)
        info_col.addSpacing(int(6 * s))
        info_col.addWidget(card, 1)

        self.portrait = PortraitView(s, self.theme)
        self.portrait.setFixedWidth(int(380 * s))
        self.portrait.tapped.connect(self.open_portrait)
        top.addLayout(info_col, 1)
        top.addWidget(self.portrait)

        # ---- архивные фото внизу
        self.arch_head = QLabel()
        self.arch_head.setObjectName("cardHead")
        self.thumb_size = (int(340 * s), int(230 * s))
        self.strip = QListWidget()
        self.strip.setFlow(QListWidget.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip.setFrameShape(QFrame.Shape.NoFrame)
        self.strip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.strip.setSpacing(0)
        self.strip.setFixedHeight(self.thumb_size[1] + int(18 * s))
        self.strip.setItemDelegate(ThumbDelegate(s, self.thumbs, self.thumb_size,
                                                 lambda: self._caps, self.theme, self.strip))
        QScroller.grabGesture(self.strip.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        self.strip.clicked.connect(lambda idx: self.open_overlay(idx.row()))

        pv.addLayout(top, 1)
        pv.addWidget(self.arch_head)
        pv.addWidget(self.strip)
        self.stack.addWidget(page)

        root.addWidget(left)
        root.addWidget(rightw, 1)

        self.overlay = Overlay(self, self.cache, s)
        self.dim = QWidget(self)
        self.dim.setObjectName("dim")
        self.dim.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.dim.hide()

    def _style(self):
        s = self.scale
        m = self.theme.mult
        f = lambda v: int(v * s)
        ff = lambda v: int(v * s * m)
        if self.theme.hc:
            P = SimpleNamespace(
                root="#000000", left="#000000", left_b="#ffffff", text="#ffffff", title="#ffffff",
                acc="#ffe600", muted="#ffffff", card="#000000", card_b="#ffffff", pill="#000000",
                pill_b="#ffe600", btn="#000000", btn_b="#ffffff", cnt="#1a1a1a", nav="#000000",
                nav_b="#ffffff", key="#000000", dim="rgba(0,0,0,225)", bw=3, badge="#ffe600",
                badge_t="#000000", chk="#ffe600", chk_t="#000000", press="#ffe600", press_t="#000000",
                err="#ff9a9a", pin_bg="#000000", disp="#1a1a1a")
        else:
            P = SimpleNamespace(
                root="qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fcf7ec, stop:0.65 #fffdf8, stop:1 #e5f2fc)",
                left="qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #091f4b, stop:0.58 #103d84, stop:1 #07559e)",
                left_b="#d8ac54", text="#203957", title="#102f63", acc="#785213", muted="#4a627a",
                card="#fffefa", card_b="#cfbd97", pill="#f9efd8", pill_b="#be9856", btn="#fffefa",
                btn_b="#9eb0c5", cnt="#18375c", nav="#193f6f", nav_b="#77a4d2", key="#183f72",
                dim="rgba(4,16,38,210)", bw=1, badge_t="#102f63", chk="#134f99", chk_t="#ffffff",
                press="#08619f", press_t="#ffffff", err="#ffb8ae", disp="#18375c")
        side_text = "#ffffff"
        side_accent = "#ffe600" if self.theme.hc else "#ffdb8b"
        side_button = P.btn if self.theme.hc else "#153e73"
        side_border = P.btn_b if self.theme.hc else "#6c94c2"
        hero_font = "'Segoe UI'" if self.theme.hc else "Georgia, 'Times New Roman'"
        return f"""
        QWidget {{ background:transparent; color:{P.text}; font-family:'Segoe UI'; }}
        #root {{ background:{P.root}; }}
        #left {{ background:{P.left}; border-right:{max(P.bw, f(3))}px solid {P.left_b}; }}
        #badge {{ background:#ffffff; border-radius:{f(24)}px; font-size:{f(42)}px; color:{P.badge_t}; }}
        #title {{ font-size:{ff(34)}px; font-weight:700; color:{side_text}; }}
        #subtitle {{ font-size:{ff(15)}px; font-weight:600; color:{side_accent}; }}
        QListWidget {{ background:transparent; outline:0; border:none; }}
        #exitBtn {{ background:{side_button}; border:{P.bw}px solid {side_border}; border-radius:{f(20)}px;
                   font-size:{ff(24)}px; font-weight:600; color:{side_text}; }}
        #exitBtn:pressed {{ background:#ef4444; border-color:#ef4444; color:#ffffff; }}
        #tool {{ background:{P.btn}; border:{P.bw}px solid {P.btn_b}; border-radius:{f(18)}px;
                font-size:{ff(22)}px; font-weight:600; color:{P.text}; padding:0 {f(18)}px; }}
        #tool:checked {{ background:{P.chk}; color:{P.chk_t}; border-color:{P.chk}; }}
        #left #tool:checked {{ border:2px solid {side_accent}; }}
        #tool:pressed {{ background:{P.press}; color:{P.press_t}; border-color:{P.press}; }}
        #era {{ color:{P.acc}; font-size:{ff(20)}px; font-weight:700; }}
        #storyHeading {{ font-family:{hero_font}; color:{P.title}; font-size:{ff(46)}px; font-weight:700; }}
        #collegeStory {{ background:{P.card}; border:{P.bw}px solid {P.card_b}; border-radius:{f(20)}px; padding:{f(26)}px; }}
        #primary {{ background:{P.chk}; color:{P.chk_t}; border:2px solid {P.chk}; padding:0 {f(28)}px; border-radius:{f(18)}px; font-size:{ff(23)}px; font-weight:700; }}
        #welcomeIcon {{ font-size:{f(130)}px; }}
        #welcome {{ font-size:{ff(36)}px; color:{P.muted}; }}
        #name {{ font-family:{hero_font}; font-size:{ff(52)}px; font-weight:700; color:{P.title}; }}
        #years {{ font-size:{ff(26)}px; font-weight:600; color:{P.acc}; background:{P.pill};
                 border:{P.bw}px solid {P.pill_b}; border-radius:{f(22)}px; padding:{f(8)}px {f(22)}px; }}
        #card {{ background:{P.card}; border:{P.bw}px solid {P.card_b}; border-radius:{f(26)}px; }}
        #cardHead {{ font-size:{ff(16)}px; font-weight:700; color:{P.acc}; }}
        #desc {{ font-size:{ff(25)}px; color:{P.text}; }}
        QScrollArea {{ background:transparent; border:none; }}
        #caption {{ font-size:{ff(22)}px; color:{side_text}; }}
        #counter {{ font-size:{ff(19)}px; font-weight:600; color:{side_text}; background:{P.cnt};
                   border-radius:{f(16)}px; padding:{f(4)}px {f(18)}px; }}
        #nav {{ background:{P.nav}; color:#ffffff; border:{P.bw}px solid {P.nav_b};
               border-radius:{f(45)}px; font-size:{f(46)}px; font-weight:600; }}
        #nav:pressed {{ background:{P.press}; color:{P.press_t}; border-color:{P.press}; }}
        #overlay {{ background:#08172c; }}
        #dim {{ background:{P.dim}; }}
        #pinTitle {{ font-size:{f(32)}px; font-weight:700; color:#ffffff; }}
        #pinDisplay {{ font-size:{f(44)}px; color:{side_accent}; min-height:{f(70)}px; background:{P.disp};
                      border-radius:{f(16)}px; }}
        #pinStatus {{ font-size:{f(20)}px; color:{P.err}; }}
        #key {{ background:{P.key}; font-size:{f(36)}px; border-radius:{f(18)}px;
               border:{P.bw}px solid {P.btn_b}; color:#ffffff; }}
        #key:pressed {{ background:{P.press}; color:{P.press_t}; }}
        #keyCancel {{ background:{P.btn}; border:{P.bw}px solid {P.btn_b}; font-size:{f(26)}px;
                     border-radius:{f(18)}px; color:{P.text}; }}
        """

    def apply_theme(self):
        self.transition.clear()
        self.setStyleSheet(self._style())
        self.list.scheduleDelayedItemsLayout()
        self.list.viewport().update()
        self.strip.viewport().update()
        self.portrait.update()
        self.render_history()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.transition.clear()
        self.overlay.setGeometry(self.rect())
        self.dim.setGeometry(self.rect())

    def open_history(self):
        self.speaker.stop()
        self.list.setCurrentRow(-1)
        self.list.clearSelection()
        self.list.scrollToTop()
        self.stack.setCurrentIndex(0)
        self.home_btn.setChecked(True)
        self.history_reader.verticalScrollBar().setValue(0)
        if self.narrator:
            self.read_current()

    def render_history(self):
        chapters = self.college.get("chapters", [])
        esc = lambda value: html.escape(tr(value, self.lang))
        px = lambda n: max(1, round(n * self.scale * self.theme.mult))
        accent = "#ffe600" if self.theme.hc else "#785213"
        ink = "#ffffff" if self.theme.hc else "#102f63"
        body = "#ffffff" if self.theme.hc else "#203957"
        self.story_period.setVisible(bool(chapters))
        self.story_heading.setText(tr(self.college.get("heading"), self.lang) or self.T("welcome"))
        parts = []
        for chapter in chapters:
            parts.append(
                f'<p style="margin-top:{px(18)}px"><span style="color:{accent};font-size:{px(20)}px">'
                f'{esc(chapter["period"])}</span></p>'
                f'<p style="margin-top:{px(6)}px"><span style="color:{ink};font-size:{px(30)}px">'
                f'<b>{esc(chapter["title"])}</b></span></p>'
                f'<p style="margin-top:{px(10)}px;margin-bottom:{px(24)}px">'
                f'<span style="color:{body};font-size:{px(25)}px">{esc(chapter["text"])}</span></p>')
        self.history_reader.setHtml("".join(parts))

    # --- язык
    def select_language(self, lang):
        if lang == self.lang:
            self.lang_btns[lang].setChecked(True)
            return
        with self.transition.switch(self.stack):
            self.set_language(lang)

    def set_language(self, lang):
        if lang not in LANGS:
            lang = "ru"
        self.speaker.stop()
        self.lang = lang
        for code, b in self.lang_btns.items():
            b.setChecked(code == lang)
        self.title_lbl.setText(self.title_for() if self.cfg.get("title") else tr(self.college.get("name"), lang) or self.title_for())
        self.sub_lbl.setText(self.T("subtitle"))
        self.exit_btn.setText("⏻   " + self.T("exit"))
        self.home_btn.setText(tr(self.college.get("history"), lang) or self.T("history"))
        self.directors_btn.setText((tr(self.college.get("leaders"), lang) or self.T("subtitle")) + "   →")
        self.home_btn.setChecked(self.stack.currentIndex() == 0)
        self.render_history()
        self.card_head.setText(self.T("history"))
        self.arch_head.setText(self.T("archive"))
        self.btn_contrast.setText("◐  " + self.T("contrast"))
        self.btn_narr.setText("🔊  " + self.T("narrator"))
        self.update_read_btn(force=True)
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.people:
            it = QListWidgetItem()
            list_period = p.years(lang)
            if p.info.get("period_label"):
                list_period += " · " + tr(p.info["period_label"], lang)
            it.setData(Qt.ItemDataRole.UserRole, (p.name(lang), list_period, p.portrait))
            self.list.addItem(it)
        if 0 <= row < len(self.people):
            self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        if 0 <= row < len(self.people):
            self.show_person(row)
        if self.narrator:
            self.read_current()

    # --- доступность
    def change_text_size(self, delta):
        self.theme.mult = max(1.0, min(1.6, round(self.theme.mult + delta, 1)))
        self.apply_theme()

    def on_contrast(self, checked):
        self.theme.hc = bool(checked)
        self.apply_theme()

    def on_narrator(self, checked):
        self.narrator = bool(checked)
        if not self.narrator:
            self.speaker.stop()
        else:
            self.read_current()

    def person_text(self, p):
        parts = [p.name(self.lang)]
        period = p.period_text(self.lang)
        if period:
            parts.append(period)
        d = p.description(self.lang)
        if d:
            parts.append(d)
        return ". ".join(x.strip().rstrip(".") for x in parts if x.strip()) + "."

    def read_current(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.people):
            self.speaker.speak(self.person_text(self.people[row]), self.lang)
        elif self.stack.currentIndex() == 0:
            self.speaker.speak(self.history_reader.toPlainText(), self.lang)

    def toggle_read(self):
        if self.speaker.is_speaking():
            self.speaker.stop()
        else:
            self.read_current()
        self.update_read_btn(force=True)

    def update_read_btn(self, force=False):
        txt = ("⏹  " + self.T("stop")) if self.speaker.is_speaking() else ("🔊  " + self.T("read"))
        if force or self.read_btn.text() != txt:
            self.read_btn.setText(txt)
            self.history_read.setText(txt)

    # --- поведение
    def _on_item(self, current, previous):
        self.speaker.stop()
        row = self.list.row(current)
        previous_row = self.list.row(previous)
        self.home_btn.setChecked(row < 0)
        with self.transition.switch(self.stack, dy=-22 if row > previous_row else 22):
            self.show_person(row)
        if self.narrator and 0 <= row < len(self.people):
            self.read_current()

    def show_person(self, row):
        if row < 0 or row >= len(self.people):
            self.stack.setCurrentIndex(0)
            return
        p = self.people[row]
        lang = self.lang
        self.name_lbl.setText(p.name(lang))
        period = p.period_text(lang)
        self.years_lbl.setWordWrap(len(period) > 35)
        self.years_lbl.setText(period)
        self.years_lbl.setVisible(bool(period))
        paras = [html.escape(x.strip()) for x in p.description(lang).split("\n") if x.strip()]
        self.desc.setText("".join(f"<p style='margin:0 0 {int(14 * self.scale)}px 0; line-height:140%'>{x}</p>"
                                  for x in paras))
        self._caps = p.captions(lang)
        self.portrait.setVisible(bool(p.portrait))
        self.portrait.set_person(self.cache.get(p.portrait) if p.portrait else None, p.name(lang))
        self.strip.clear()
        for ph in p.photos:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, ph)
            self.strip.addItem(it)
        self.strip.horizontalScrollBar().setValue(0)
        has = bool(p.photos)
        self.arch_head.setVisible(has)
        self.strip.setVisible(has)
        self.stack.setCurrentIndex(1)

    def _show_overlay(self, photos, captions, index):
        with self.transition.switch(self):
            self.overlay.gallery.set_photos(photos, captions, index)
            self.overlay.setGeometry(self.rect())
            self.overlay.show()
            self.overlay.raise_()

    def open_overlay(self, index=0):
        row = self.list.currentRow()
        if 0 <= row < len(self.people) and self.people[row].photos:
            p = self.people[row]
            self._show_overlay(p.photos, p.captions(self.lang), index)

    def open_portrait(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.people) and self.people[row].portrait:
            self._show_overlay([self.people[row].portrait], {}, 0)

    def go_home(self):
        """Бездействие: сброс к начальному экрану, языку и настройкам доступности."""
        self.transition.clear()
        self.speaker.stop()
        self.overlay.hide()
        self.narrator = False
        self.btn_narr.blockSignals(True)
        self.btn_narr.setChecked(False)
        self.btn_narr.blockSignals(False)
        self.theme.hc = False
        self.theme.mult = 1.0
        self.btn_contrast.blockSignals(True)
        self.btn_contrast.setChecked(False)
        self.btn_contrast.blockSignals(False)
        self.list.blockSignals(True)
        self.list.setCurrentRow(-1)
        self.list.clearSelection()
        self.list.scrollToTop()
        self.list.blockSignals(False)
        self.stack.setCurrentIndex(0)
        self.set_language(self.default_lang)
        self.apply_theme()

    def eventFilter(self, obj, ev):
        if self.idle.interval() > 0 and ev.type() in (QEvent.Type.MouseButtonPress,
                                                       QEvent.Type.TouchBegin,
                                                       QEvent.Type.KeyPress):
            self.idle.start()
        return False

    def _keep_top(self):
        if not self._pin_open:
            self.raise_()
            self.activateWindow()

    # --- пароль и выход
    def _verify(self, pin):
        now = time.time()
        if now < self._locked_until:
            return "locked"
        if hash_pin(pin, self.cfg["salt"]) == self.cfg["pin_hash"]:
            self._fails = 0
            return "ok"
        self._fails += 1
        if self._fails >= 5:
            self._fails = 0
            self._locked_until = now + 60
            return "locked"
        return "bad"

    def ask_password(self):
        if self._pin_open:
            return
        self.transition.clear()
        self._pin_open = True
        self.dim.setGeometry(self.rect())
        self.dim.show()
        self.dim.raise_()
        dlg = PinDialog(self, self._verify, self.scale, self.theme.hc, self.T)
        dlg.adjustSize()
        dlg.move(self.geometry().center() - dlg.rect().center())
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        self.dim.hide()
        self._pin_open = False
        if ok:
            self.shutdown()

    def shutdown(self):
        self._allow_close = True
        self.speaker.stop()
        if self.lock:
            self.lock.remove()
        QApplication.quit()

    def closeEvent(self, e):
        if self._allow_close:
            e.accept()
        else:
            e.ignore()


# ----------------------------------------------------------------- запуск
def presentation_images(archive):
    """Embedded pictures in slide order. Keep captions for the operator's review."""
    def relationships(member):
        rels = posixpath.join(posixpath.dirname(member), "_rels", posixpath.basename(member) + ".rels")
        if rels not in archive.NameToInfo:
            return {}
        root = ET.fromstring(archive.read(rels))
        result = {}
        for rel in root:
            if rel.get("TargetMode") == "External":
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(member), rel.get("Target", ""))).lstrip("/")
            if target in archive.NameToInfo:
                result[rel.get("Id")] = target
        return result

    rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    presentation = "ppt/presentation.xml"
    slide_paths = relationships(presentation)
    root = ET.fromstring(archive.read(presentation))
    entries = []
    for index, slide in enumerate(root.findall(".//{*}sldIdLst/{*}sldId"), 1):
        path = slide_paths.get(slide.get(rel_id + "id"))
        if not path:
            continue
        content = ET.fromstring(archive.read(path))
        words = " ".join(n.text or "" for n in content.findall(".//{*}t"))
        files = relationships(path)
        seen = set()
        for blip in content.findall(".//{*}blip"):
            image = files.get(blip.get(rel_id + "embed"))
            if image and image not in seen and Path(image).suffix.lower() in IMG_EXT:
                seen.add(image)
                entries.append((index, image, words))
    return entries


class CropPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.image = QImage()
        self.selection = QRect()
        self.start = None
        self.setMinimumSize(320, 200)

    def image_rect(self):
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRect(QPoint(), size)
        rect.moveCenter(self.rect().center())
        return rect

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#103661"))
        if not self.image.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(self.image_rect(), self.image)
        if self.selection.isValid():
            p.setPen(QPen(QColor("#ffce58"), 3))
            p.drawRect(self.selection)

    def resizeEvent(self, event):
        self.selection = QRect()
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        point = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(point):
            self.start = point
            self.selection = QRect()
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.selection = QRect(self.start, event.position().toPoint()).normalized().intersected(self.image_rect())
            self.update()

    def mouseReleaseEvent(self, event):
        self.mouseMoveEvent(event)
        self.start = None
        if self.selection.width() < 5 or self.selection.height() < 5:
            self.selection = QRect()
        self.update()

    def cropped(self):
        if self.selection.isEmpty():
            return self.image
        rect = self.image_rect()
        selection = self.selection.translated(-rect.topLeft())
        sx, sy = self.image.width() / rect.width(), self.image.height() / rect.height()
        return self.image.copy(QRectF(selection.x()*sx, selection.y()*sy,
                                      selection.width()*sx, selection.height()*sy).toAlignedRect())


def import_portraits():
    app = QApplication(sys.argv)
    path, _ = QFileDialog.getOpenFileName(None, "Открыть презентацию колледжа", "", "PowerPoint (*.pptx)")
    if not path:
        return
    people = load_people()
    if not people:
        QMessageBox.warning(None, "Портреты", "Папка data с карточками директоров не найдена.")
        return
    try:
        with ZipFile(path) as archive:
            entries = presentation_images(archive)
            if not entries:
                QMessageBox.information(None, "Портреты", "В слайдах не найдены встроенные фотографии.")
                return
            dialog = QDialog()
            dialog.setWindowTitle("Портреты директоров из презентации")
            dialog.resize(980, 700)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("Выберите изображение. Чтобы вырезать портрет, обведите лицо и плечи мышью."))
            images = QComboBox()
            for slide, member, words in entries:
                images.addItem(f"Слайд {slide} · {Path(member).name}   {words[:75]}")
            layout.addWidget(images)
            preview = CropPreview()
            layout.addWidget(preview, 1)
            row = QHBoxLayout()
            directors = QComboBox()
            directors.addItem("Выберите директора")
            directors.addItems([person.name("ru") for person in people])
            row.addWidget(directors, 1)
            save = QPushButton("Сохранить портрет")
            row.addWidget(save)
            layout.addLayout(row)
            status = QLabel()
            layout.addWidget(status)

            def select_image(index):
                _, member, words = entries[index]
                preview.image = QImage.fromData(archive.read(member))
                preview.selection = QRect()
                preview.start = None
                preview.update()
                candidates = [i for i, person in enumerate(people, 1)
                              if person.folder.casefold() in words.casefold()]
                directors.setCurrentIndex(candidates[0] if len(candidates) == 1 else 0)
                status.setText("Изображение не читается." if preview.image.isNull() else "")
                save.setEnabled(not preview.image.isNull())

            def save_portrait():
                index = directors.currentIndex() - 1
                if index < 0:
                    status.setText("Сначала выберите директора.")
                    return
                person = people[index]
                target = DATA_DIR / person.folder / "portrait.jpg"
                if target.exists() and QMessageBox.question(dialog, "Замена портрета", person.name("ru") + " — заменить портрет?") != QMessageBox.StandardButton.Yes:
                    return
                atomic_file = QSaveFile(str(target))
                if (not atomic_file.open(QIODevice.OpenModeFlag.WriteOnly)
                        or not preview.cropped().save(atomic_file, "JPEG", 94) or not atomic_file.commit()):
                    status.setText("Ошибка записи портрета. Проверьте права на папку data.")
                    return
                status.setText("Портрет сохранён · " + person.name("ru"))

            images.currentIndexChanged.connect(select_image)
            save.clicked.connect(save_portrait)
            select_image(0)
            dialog.exec()
    except (OSError, BadZipFile, KeyError, ET.ParseError, RuntimeError) as exc:
        QMessageBox.warning(None, "Ошибка чтения презентации", str(exc))


def main():
    if sys.argv[1:] == ["--import-portraits"]:
        return import_portraits()
    if len(sys.argv) >= 3 and sys.argv[1] == "--setpin":
        pin = sys.argv[2]
        if pin.isdigit() and 3 <= len(pin) <= 12:
            cfg = load_config()
            cfg["salt"] = secrets.token_hex(8)
            cfg["pin_hash"] = hash_pin(pin, cfg["salt"])
            save_config(cfg)
        return

    cfg = load_config()
    people = load_people()
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    scr = app.primaryScreen()
    sz = scr.size()  # логические пиксели (с учётом масштаба Windows)
    # базовый макет рассчитан на 1920x1080; на 4K/65" всё увеличивается пропорционально
    scale = max(0.5, min(3.0, min(sz.width() / 1920.0, sz.height() / 1080.0)))
    global MAX_SIDE
    MAX_SIDE = int(max(sz.width(), sz.height()) * scr.devicePixelRatio())

    win = Kiosk(cfg, people, scale)
    app.installEventFilter(win)
    win.showFullScreen()
    win.lock = install_keyboard_lock()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
