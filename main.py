import json
import os
import sys
import time
import math
import subprocess
import shutil
from dataclasses import dataclass, asdict, field
from pathlib import Path
from collections import deque

import psutil
import pyqtgraph as pg

from PySide6.QtCore import (
    Qt, QTimer, QSize, QRunnable, QThreadPool, Signal, QObject, QPoint
)
from PySide6.QtGui import QAction, QPixmap, QImageReader, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QToolButton,
    QDialog, QTabWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit,
    QPushButton, QFileDialog, QListWidget, QListWidgetItem, QCheckBox,
    QSystemTrayIcon, QMenu, QStyle, QTableWidget, QTableWidgetItem, QHeaderView,
    QGraphicsBlurEffect, QComboBox, QStackedWidget, QSizePolicy,
    QGroupBox, QColorDialog, QSlider, QTextEdit
)

APP_NAME = "NetPulse"
APP_VERSION = "0.1"



def app_config_dir() -> Path:
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", home))
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = home / ".config"
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def app_assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def project_backgrounds_dir() -> Path:
    d = app_assets_dir() / "backgrounds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def appdata_assets_dir() -> Path:
    d = app_config_dir() / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backgrounds_dir() -> Path:
    d = appdata_assets_dir() / "backgrounds"
    d.mkdir(parents=True, exist_ok=True)
    return d


SETTINGS_PATH = app_config_dir() / "settings.json"



def is_image_readable(path: Path) -> bool:
    try:
        r = QImageReader(str(path))
        return r.canRead()
    except Exception:
        return False


def safe_pixmap(path: Path):
    if not is_image_readable(path):
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    return pm




def _copy_file_safe(src: Path, dst: Path) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return True
    except Exception:
        return False


def ensure_builtin_backgrounds_in_appdata(default_name: str = "BaseImage1.png") -> None:
    src_dir = project_backgrounds_dir()
    dst_dir = backgrounds_dir()

    src_default = src_dir / default_name
    dst_default = dst_dir / default_name

    if src_default.exists():
        if (not dst_default.exists()) or (not is_image_readable(dst_default)):
            _copy_file_safe(src_default, dst_default)

    if not any(dst_dir.iterdir()):
        for p in src_dir.iterdir():
            if p.is_file() and p.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"] and is_image_readable(p):
                _copy_file_safe(p, dst_dir / p.name)




@dataclass
class Settings:
    mode: str = "simple"
    tray_enabled: bool = True
    tray_click_popup: bool = True
    autostart: bool = False

    remember_geometry: bool = True
    window_x: int = -1
    window_y: int = -1

    simple_w: int = 420
    simple_h: int = 190
    adv_w: int = 1050
    adv_h: int = 780

    # Мониторинг
    ping_host: str = "1.1.1.1"
    stats_refresh_ms: int = 1000
    ping_refresh_ms: int = 1500

    follow_graph: bool = True

    # выбор адаптеров
    simple_adapter: str = "active"
    graph_adapter: str = "active"
    monitored_adapters: list = field(default_factory=list)


    graph_color_mode: str = "auto"
    graph_custom_color: str = "#4db7ff"
    line_width: int = 1


    good_ping_ms: int = 60
    ok_ping_ms: int = 150
    good_mbps: float = 5.0
    ok_mbps: float = 0.5

    # Кастомизация
    use_builtin_background: bool = True
    builtin_background_name: str = "BaseImage1.png"  # дефолт
    background_path: str = ""

    window_opacity: int = 30
    transparent_mode: bool = True
    blur_simple: bool = False
    blur_advanced: bool = True
    blur_radius: int = 18


def save_settings(s: Settings) -> None:
    SETTINGS_PATH.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")


def load_settings() -> Settings:
    ensure_builtin_backgrounds_in_appdata(default_name="BaseImage1.png")

    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            base = asdict(Settings())
            base.update(data)
            s = Settings(**base)

            if s.mode not in ("simple", "advanced"):
                s.mode = "simple"
            if not s.ping_host:
                s.ping_host = "1.1.1.1"
            if s.graph_color_mode not in ("auto", "custom"):
                s.graph_color_mode = "auto"
            if not s.graph_custom_color:
                s.graph_custom_color = "#4db7ff"
            if not isinstance(s.monitored_adapters, list):
                s.monitored_adapters = []

            s.stats_refresh_ms = int(max(250, min(10000, s.stats_refresh_ms)))
            s.ping_refresh_ms = int(max(500, min(20000, s.ping_refresh_ms)))
            s.blur_radius = int(max(0, min(60, s.blur_radius)))
            s.window_opacity = int(max(0, min(60, s.window_opacity)))
            s.line_width = int(max(1, min(6, s.line_width)))


            if s.use_builtin_background and s.builtin_background_name:
                ensure_builtin_backgrounds_in_appdata(default_name=s.builtin_background_name)


            if not getattr(s, "simple_adapter", None):
                s.simple_adapter = "active"

            return s
        except Exception:
            pass


    s = Settings()
    ensure_builtin_backgrounds_in_appdata(default_name=s.builtin_background_name)
    save_settings(s)
    return s



def set_windows_autostart(app_name: str, enable: bool) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = f'"{sys.executable}" "{Path(__file__).resolve()}"'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
    except Exception:
        pass




def list_adapters() -> list[str]:
    return sorted(psutil.net_if_stats().keys())


def pick_active_adapter_name() -> str:
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()

    candidates = []
    for name, st in stats.items():
        if not st.isup:
            continue
        if name.lower().startswith(("lo", "loopback")):
            continue
        low = name.lower()
        if any(x in low for x in
               ["virtual", "vmware", "hyper-v", "vbox", "loopback", "tunnel", "tap", "tun", "vpn", "wintun",
                "wireguard"]):
            continue

        ip_score = 0
        for a in addrs.get(name, []):
            fam = getattr(a, "family", None)
            if fam and str(fam).endswith("AF_INET") and a.address and a.address != "127.0.0.1":
                ip_score += 10

        speed_score = st.speed if st.speed else 0
        candidates.append((ip_score + speed_score / 10, name))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    for name, st in stats.items():
        if st.isup:
            return name
    return "Нет сети"


def ping_once(host: str = "1.1.1.1", timeout_ms: int = 800):

    try:
        if sys.platform.startswith("win"):
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
        else:
            cmd = ["ping", "-c", "1", host]


        creationflags = 0
        startupinfo = None
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=creationflags,
            startupinfo=startupinfo
        )

        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            return None

        s = out.lower().replace(" ", "")
        idx = s.find("time=")
        if idx != -1:
            t = s[idx + 5:]
            end = t.find("ms")
            if end != -1:
                val = t[:end].replace("<", "")
                try:
                    return int(round(float(val)))
                except Exception:
                    return None

        idx = s.find("время=")
        if idx != -1:
            t = s[idx + 6:]
            end = t.find("мс")
            if end != -1:
                val = t[:end].replace("<", "")
                try:
                    return int(round(float(val)))
                except Exception:
                    return None

        return None
    except Exception:
        return None




class PingSignals(QObject):
    done = Signal(object)  # int|None


class PingTask(QRunnable):
    def __init__(self, host: str):
        super().__init__()
        self.host = host
        self.signals = PingSignals()

    def run(self):
        ms = ping_once(self.host)
        self.signals.done.emit(ms)



GREEN = "#4dff88"
YELLOW = "#ffd24d"
RED = "#ff4d4d"
BLUE = "#4db7ff"


def quality_color(value, good: float, ok: float, invert: bool = False) -> str:
    if value is None:
        return RED
    try:
        v = float(value)
    except Exception:
        return RED
    if math.isnan(v) or math.isinf(v):
        return RED

    if invert:  # ping: меньше лучше
        if v <= good:
            return GREEN
        if v <= ok:
            return YELLOW
        return RED
    else:  # mbps: больше лучше
        if v >= good:
            return GREEN
        if v >= ok:
            return YELLOW
        return RED


def split_series_by_quality(xs, ys, good, ok, invert=False):
    nan = float("nan")
    x_g, y_g = [], []
    x_y, y_y = [], []
    x_r, y_r = [], []

    for x, y in zip(xs, ys):
        col = quality_color(y, good, ok, invert=invert)
        if col == GREEN:
            x_g.append(x);
            y_g.append(float(y))
            x_y.append(x);
            y_y.append(nan)
            x_r.append(x);
            y_r.append(nan)
        elif col == YELLOW:
            x_g.append(x);
            y_g.append(nan)
            x_y.append(x);
            y_y.append(float(y))
            x_r.append(x);
            y_r.append(nan)
        else:
            x_g.append(x);
            y_g.append(nan)
            x_y.append(x);
            y_y.append(nan)
            x_r.append(x);
            y_r.append(float(y))
    return (x_g, y_g), (x_y, y_y), (x_r, y_r)



class SettingsDialog(QDialog):
    def __init__(self, parent, settings: Settings):
        super().__init__(parent)
        self.setModal(True)
        self.settings = settings
        self.setWindowTitle(f"Настройки {APP_NAME}")

        self.tabs = QTabWidget(self)

        self._tab_basic = self._build_basic_tab()
        self._tab_monitor = self._build_monitor_tab()
        self._tab_custom = self._build_custom_tab()
        self._tab_about = self._build_about_tab()

        self.tabs.addTab(self._tab_basic, "Основное")
        self.tabs.addTab(self._tab_monitor, "Мониторинг")
        self.tabs.addTab(self._tab_custom, "Кастомизация")
        self.tabs.addTab(self._tab_about, "О программе")

        btn_save = QPushButton("Сохранить")
        btn_cancel = QPushButton("Отмена")
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_save)

        root = QVBoxLayout(self)
        root.addWidget(self.tabs)
        root.addLayout(bottom)

        self._apply_dialog_style()
        self.resize(860, 680)

    def _apply_dialog_style(self):
        self.setStyleSheet("""
            QDialog { background: #0f1116; color: #e9edf2; }
            QTabWidget::pane { border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; }
            QTabBar::tab {
                background: rgba(255,255,255,0.06);
                padding: 10px 14px;
                margin-right: 6px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                color: rgba(255,255,255,0.86);
            }
            QTabBar::tab:selected { background: rgba(255,255,255,0.12); color: #ffffff; }
            QGroupBox {
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                margin-top: 10px;
                padding: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: rgba(255,255,255,0.90); }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px;
                padding: 7px 10px;
                color: #e9edf2;
            }
            QComboBox::drop-down { border: none; }
            QCheckBox { padding: 4px 0; }
            QPushButton {
                background: rgba(255,255,255,0.10);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 10px;
                padding: 8px 14px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.16); }
            QListWidget {
                background: rgba(0,0,0,0.20);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px;
            }
        """)

    def _build_basic_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        gb = QGroupBox("Система")
        form = QFormLayout(gb)

        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["simple", "advanced"])
        self.cb_mode.setCurrentText(self.settings.mode)

        self.chk_autostart = QCheckBox("Запускать при старте системы (Windows)")
        self.chk_autostart.setChecked(self.settings.autostart)

        self.chk_tray = QCheckBox("Показывать в трее")
        self.chk_tray.setChecked(self.settings.tray_enabled)

        self.chk_tray_popup = QCheckBox("Popup при клике по трею")
        self.chk_tray_popup.setChecked(self.settings.tray_click_popup)

        self.chk_remember_geom = QCheckBox("Сохранять позицию окна (координаты) и применять при запуске")
        self.chk_remember_geom.setChecked(self.settings.remember_geometry)

        self.sp_simple_w = QSpinBox();
        self.sp_simple_w.setRange(280, 1600);
        self.sp_simple_w.setValue(self.settings.simple_w)
        self.sp_simple_h = QSpinBox();
        self.sp_simple_h.setRange(140, 1200);
        self.sp_simple_h.setValue(self.settings.simple_h)
        self.sp_adv_w = QSpinBox();
        self.sp_adv_w.setRange(600, 2400);
        self.sp_adv_w.setValue(self.settings.adv_w)
        self.sp_adv_h = QSpinBox();
        self.sp_adv_h.setRange(500, 1800);
        self.sp_adv_h.setValue(self.settings.adv_h)

        row_simple = QWidget()
        rsl = QHBoxLayout(row_simple);
        rsl.setContentsMargins(0, 0, 0, 0);
        rsl.setSpacing(8)
        rsl.addWidget(QLabel("W"));
        rsl.addWidget(self.sp_simple_w)
        rsl.addWidget(QLabel("H"));
        rsl.addWidget(self.sp_simple_h)
        rsl.addStretch(1)

        row_adv = QWidget()
        ral = QHBoxLayout(row_adv);
        ral.setContentsMargins(0, 0, 0, 0);
        ral.setSpacing(8)
        ral.addWidget(QLabel("W"));
        ral.addWidget(self.sp_adv_w)
        ral.addWidget(QLabel("H"));
        ral.addWidget(self.sp_adv_h)
        ral.addStretch(1)

        form.addRow("Режим:", self.cb_mode)
        form.addRow(self.chk_autostart)
        form.addRow(self.chk_tray)
        form.addRow(self.chk_tray_popup)
        form.addRow(self.chk_remember_geom)
        form.addRow("Размер окна (Simple):", row_simple)
        form.addRow("Размер окна (Advanced):", row_adv)

        l.addWidget(gb)
        l.addStretch(1)
        return w

    def _build_monitor_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        gb_main = QGroupBox("Мониторинг")
        form = QFormLayout(gb_main)

        self.ed_ping_host = QLineEdit(self.settings.ping_host)

        self.sp_stats = QSpinBox()
        self.sp_stats.setRange(250, 10000)
        self.sp_stats.setSingleStep(250)
        self.sp_stats.setValue(self.settings.stats_refresh_ms)

        self.sp_ping = QSpinBox()
        self.sp_ping.setRange(500, 20000)
        self.sp_ping.setSingleStep(250)
        self.sp_ping.setValue(self.settings.ping_refresh_ms)

        self.chk_follow = QCheckBox("Следовать за графиком (синхронизировать ось времени)")
        self.chk_follow.setChecked(self.settings.follow_graph)

        self.cb_simple_adapter = QComboBox()
        self.cb_simple_adapter.addItem("active")
        for nic in list_adapters():
            self.cb_simple_adapter.addItem(nic)
        cur_simple = self.settings.simple_adapter if self.settings.simple_adapter else "active"
        if self.cb_simple_adapter.findText(cur_simple) == -1:
            cur_simple = "active"
        self.cb_simple_adapter.setCurrentText(cur_simple)


        self.cb_color_mode = QComboBox()
        self.cb_color_mode.addItems(["auto", "custom"])
        self.cb_color_mode.setCurrentText(self.settings.graph_color_mode)

        self.btn_pick_color = QPushButton("Выбрать цвет…")
        self.lbl_color = QLabel(self.settings.graph_custom_color)
        self.lbl_color.setStyleSheet(f"color:{self.settings.graph_custom_color}; font-weight:700;")
        self.btn_pick_color.clicked.connect(self._pick_color)

        row_color = QWidget()
        rcl = QHBoxLayout(row_color);
        rcl.setContentsMargins(0, 0, 0, 0);
        rcl.setSpacing(10)
        rcl.addWidget(self.cb_color_mode)
        rcl.addWidget(self.btn_pick_color)
        rcl.addWidget(self.lbl_color)
        rcl.addStretch(1)

        self.sp_line_width = QSpinBox()
        self.sp_line_width.setRange(1, 6)
        self.sp_line_width.setValue(self.settings.line_width)


        self.cb_graph_adapter = QComboBox()
        self.cb_graph_adapter.addItem("active")
        for nic in list_adapters():
            self.cb_graph_adapter.addItem(nic)
        cur = self.settings.graph_adapter if self.settings.graph_adapter else "active"
        if self.cb_graph_adapter.findText(cur) == -1:
            cur = "active"
        self.cb_graph_adapter.setCurrentText(cur)

        self.list_table_adapters = QListWidget()
        self.list_table_adapters.setSelectionMode(QListWidget.MultiSelection)
        selected = set(self.settings.monitored_adapters or [])
        for nic in list_adapters():
            it = QListWidgetItem(nic)
            self.list_table_adapters.addItem(it)
            if nic in selected:
                it.setSelected(True)

        self.sp_good_ping = QSpinBox();
        self.sp_good_ping.setRange(1, 2000);
        self.sp_good_ping.setValue(self.settings.good_ping_ms)
        self.sp_ok_ping = QSpinBox();
        self.sp_ok_ping.setRange(1, 5000);
        self.sp_ok_ping.setValue(self.settings.ok_ping_ms)
        self.sp_good_mbps = QDoubleSpinBox();
        self.sp_good_mbps.setRange(0.0, 100000.0);
        self.sp_good_mbps.setDecimals(2);
        self.sp_good_mbps.setValue(self.settings.good_mbps)
        self.sp_ok_mbps = QDoubleSpinBox();
        self.sp_ok_mbps.setRange(0.0, 100000.0);
        self.sp_ok_mbps.setDecimals(2);
        self.sp_ok_mbps.setValue(self.settings.ok_mbps)

        form.addRow("Ping target:", self.ed_ping_host)
        form.addRow("Обновление скоростей/таблицы (мс):", self.sp_stats)
        form.addRow("Обновление Ping (мс):", self.sp_ping)
        form.addRow(self.chk_follow)
        form.addRow("SIMPLE: адаптер:", self.cb_simple_adapter)
        form.addRow("Цвет графика:", row_color)
        form.addRow("Толщина линии:", self.sp_line_width)
        form.addRow("ADV графики: адаптер", self.cb_graph_adapter)
        form.addRow("Таблица: адаптеры", self.list_table_adapters)
        form.addRow("Ping зелёный ≤ (мс):", self.sp_good_ping)
        form.addRow("Ping жёлтый ≤ (мс):", self.sp_ok_ping)
        form.addRow("Mbps зелёный ≥ :", self.sp_good_mbps)
        form.addRow("Mbps жёлтый ≥ :", self.sp_ok_mbps)

        l.addWidget(gb_main)
        l.addStretch(1)
        return w

    def _build_custom_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        gb_bg = QGroupBox("Фон")
        form_bg = QFormLayout(gb_bg)

        self.chk_builtin = QCheckBox("Использовать установленные фоны (AppData\\NetPulse\\assets\\backgrounds)")
        self.chk_builtin.setChecked(self.settings.use_builtin_background)

        self.list_bg = QListWidget()
        self._load_builtin_backgrounds()

        self.ed_custom = QLineEdit(self.settings.background_path)
        self.btn_pick = QPushButton("Выбрать файл…")
        self.btn_pick.clicked.connect(self._pick_background_file)

        row_custom = QWidget()
        row_l = QHBoxLayout(row_custom)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(10)
        row_l.addWidget(self.ed_custom, 1)
        row_l.addWidget(self.btn_pick)

        form_bg.addRow(self.chk_builtin)
        form_bg.addRow("Установленные:", self.list_bg)
        form_bg.addRow("Свой фон:", row_custom)

        gb_view = QGroupBox("Вид окна")
        form_v = QFormLayout(gb_view)

        self.chk_transparent = QCheckBox("Прозрачный режим (оверлей на фоне)")
        self.chk_transparent.setChecked(self.settings.transparent_mode)

        self.chk_blur_simple = QCheckBox("Blur в Simple")
        self.chk_blur_simple.setChecked(self.settings.blur_simple)

        self.chk_blur_adv = QCheckBox("Blur в Advanced")
        self.chk_blur_adv.setChecked(self.settings.blur_advanced)

        self.sp_blur = QSpinBox()
        self.sp_blur.setRange(0, 60)
        self.sp_blur.setValue(self.settings.blur_radius)

        self.sl_opacity = QSlider(Qt.Horizontal)
        self.sl_opacity.setRange(0, 60)
        self.sl_opacity.setValue(self.settings.window_opacity)
        self.lbl_op = QLabel(str(self.settings.window_opacity))
        self.sl_opacity.valueChanged.connect(lambda v: self.lbl_op.setText(str(v)))

        row_op = QWidget()
        rol = QHBoxLayout(row_op);
        rol.setContentsMargins(0, 0, 0, 0);
        rol.setSpacing(10)
        rol.addWidget(self.sl_opacity, 1)
        rol.addWidget(self.lbl_op)

        form_v.addRow(self.chk_transparent)
        form_v.addRow(self.chk_blur_simple)
        form_v.addRow(self.chk_blur_adv)
        form_v.addRow("Blur радиус:", self.sp_blur)
        form_v.addRow("Насыщенность подложки (0..60):", row_op)

        l.addWidget(gb_bg)
        l.addWidget(gb_view)
        l.addStretch(1)
        return w

    def _build_about_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        gb = QGroupBox("О программе")
        v = QVBoxLayout(gb)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet("""
            QTextEdit {
                background: rgba(0,0,0,0.25);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                padding: 10px;
                color: rgba(255,255,255,0.90);
            }
        """)
        text.setText(
            """
            NetPulse - одна из самых простых и оптимизированных программ 
            по мониторингу сети. Она позволяет отслеживать текущий трафик и пинг, а огромное
            кол-во кастомизации позволит ее использовать любому пользователю!
            
            Version: 0.0.1 by DeziXsteroid
            """
        )
        v.addWidget(text)
        l.addWidget(gb)
        l.addStretch(1)
        return w

    def _load_builtin_backgrounds(self):
        ensure_builtin_backgrounds_in_appdata(default_name=self.settings.builtin_background_name)

        self.list_bg.clear()
        files = sorted([p for p in backgrounds_dir().iterdir()
                        if p.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]])
        readable = [p for p in files if is_image_readable(p)]
        for p in readable:
            it = QListWidgetItem(p.name)
            self.list_bg.addItem(it)
            if p.name == self.settings.builtin_background_name:
                self.list_bg.setCurrentItem(it)

    def _pick_background_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать фон", str(Path.home()),
                                              "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.ed_custom.setText(path)

    def _pick_color(self):
        col = QColorDialog.getColor(QColor(self.settings.graph_custom_color), self, "Цвет графика")
        if col.isValid():
            hexv = col.name()
            self.lbl_color.setText(hexv)
            self.lbl_color.setStyleSheet(f"color:{hexv}; font-weight:700;")

    def apply_to_settings(self):

        self.settings.mode = self.cb_mode.currentText().strip()
        self.settings.autostart = self.chk_autostart.isChecked()
        self.settings.tray_enabled = self.chk_tray.isChecked()
        self.settings.tray_click_popup = self.chk_tray_popup.isChecked()
        self.settings.remember_geometry = self.chk_remember_geom.isChecked()

        self.settings.simple_w = int(self.sp_simple_w.value())
        self.settings.simple_h = int(self.sp_simple_h.value())
        self.settings.adv_w = int(self.sp_adv_w.value())
        self.settings.adv_h = int(self.sp_adv_h.value())


        self.settings.ping_host = self.ed_ping_host.text().strip() or "1.1.1.1"
        self.settings.stats_refresh_ms = int(self.sp_stats.value())
        self.settings.ping_refresh_ms = int(self.sp_ping.value())
        self.settings.follow_graph = self.chk_follow.isChecked()

        self.settings.simple_adapter = self.cb_simple_adapter.currentText().strip() or "active"

        self.settings.graph_color_mode = self.cb_color_mode.currentText().strip()
        self.settings.line_width = int(self.sp_line_width.value())
        self.settings.graph_custom_color = self.lbl_color.text().strip() or self.settings.graph_custom_color

        self.settings.graph_adapter = self.cb_graph_adapter.currentText().strip() or "active"
        self.settings.monitored_adapters = [it.text() for it in self.list_table_adapters.selectedItems()]

        self.settings.good_ping_ms = int(self.sp_good_ping.value())
        self.settings.ok_ping_ms = int(self.sp_ok_ping.value())
        self.settings.good_mbps = float(self.sp_good_mbps.value())
        self.settings.ok_mbps = float(self.sp_ok_mbps.value())


        self.settings.use_builtin_background = self.chk_builtin.isChecked()
        cur = self.list_bg.currentItem()
        self.settings.builtin_background_name = cur.text() if cur else ""
        self.settings.background_path = self.ed_custom.text().strip()

        self.settings.transparent_mode = self.chk_transparent.isChecked()
        self.settings.blur_simple = self.chk_blur_simple.isChecked()
        self.settings.blur_advanced = self.chk_blur_adv.isChecked()
        self.settings.blur_radius = int(self.sp_blur.value())
        self.settings.window_opacity = int(self.sl_opacity.value())

        if self.settings.use_builtin_background and self.settings.builtin_background_name:
            ensure_builtin_backgrounds_in_appdata(default_name=self.settings.builtin_background_name)



class NetPulseWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()

        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._dragging = False
        self._drag_offset = QPoint(0, 0)
        self._save_geom_timer = QTimer(self)
        self._save_geom_timer.setSingleShot(True)
        self._save_geom_timer.timeout.connect(self._persist_geometry)

        self.thread_pool = QThreadPool.globalInstance()


        self.bg = QLabel(self)
        self.bg.setScaledContents(True)

        self.blur_effect = QGraphicsBlurEffect(self)
        self.blur_effect.setBlurRadius(self.settings.blur_radius)

        self.root = QWidget(self)
        self.root.setObjectName("root")
        self.root.setAttribute(Qt.WA_TranslucentBackground, True)


        self.btn_gear = QToolButton()
        self.btn_gear.setCursor(Qt.PointingHandCursor)
        self.btn_gear.setToolTip("Настройки")
        sp = getattr(QStyle.StandardPixmap, "SP_FileDialogDetailedView", QStyle.StandardPixmap.SP_FileDialogInfoView)
        self.btn_gear.setIcon(self.style().standardIcon(sp))
        self.btn_gear.setIconSize(QSize(18, 18))
        self.btn_gear.clicked.connect(self.open_settings)

        self.lbl_connected = QLabel("Подключено — …")
        self.lbl_connected.setObjectName("connected")

        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        header.setSpacing(10)
        header.addWidget(self.btn_gear, 0, Qt.AlignLeft | Qt.AlignTop)
        header.addWidget(self.lbl_connected, 1, Qt.AlignLeft | Qt.AlignVCenter)


        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.page_simple = self._build_simple_page()
        self.page_adv = self._build_adv_page()

        self.stack.addWidget(self.page_simple)
        self.stack.addWidget(self.page_adv)


        root_l = QVBoxLayout(self.root)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)
        root_l.addLayout(header)
        root_l.addWidget(self.stack, 1)


        self.active_adapter = pick_active_adapter_name()
        self.lbl_connected.setText(f"Подключено — {self.active_adapter}")


        self.nic_last = {}
        self.nic_speed_total_mbps = {}
        self.nic_speed_down_mbps = {}
        self.nic_speed_up_mbps = {}
        self.nic_sent_mb = {}
        self.nic_recv_mb = {}

        io = psutil.net_io_counters()
        self.total_sent_mb = io.bytes_sent / (1024 * 1024)
        self.total_recv_mb = io.bytes_recv / (1024 * 1024)

        self.last_ping_ms = None


        self.last_mbps_simple_total = 0.0
        self.last_mbps_simple_down = 0.0
        self.last_mbps_simple_up = 0.0

        self.last_mbps_graph_total = 0.0
        self.last_mbps_graph_down = 0.0
        self.last_mbps_graph_up = 0.0


        self.simple_smooth_len = 10
        self.simple_hist_total = deque([0.0] * self.simple_smooth_len, maxlen=self.simple_smooth_len)
        self.simple_hist_down = deque([0.0] * self.simple_smooth_len, maxlen=self.simple_smooth_len)
        self.simple_hist_up = deque([0.0] * self.simple_smooth_len, maxlen=self.simple_smooth_len)

        self.ping_sent = 0
        self.ping_ok = 0
        self.ping_fail = 0


        self.buf_len = 240
        now = time.time()
        self.t_hist = deque([now] * self.buf_len, maxlen=self.buf_len)
        self.mbps_hist = deque([0.0] * self.buf_len, maxlen=self.buf_len)  # total
        self.ping_hist = deque([float("nan")] * self.buf_len, maxlen=self.buf_len)


        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.tick_stats)
        self.stats_timer.start(self.settings.stats_refresh_ms)

        self.ping_timer = QTimer(self)
        self.ping_timer.timeout.connect(self.request_ping)
        self.ping_timer.start(self.settings.ping_refresh_ms)


        self.tray = None
        self.tray_update_timer = None
        self._setup_tray()


        self._apply_styles()
        self._update_background()
        self._apply_mode_and_geometry()
        self._apply_blur_for_mode()
        self._apply_graph_follow()
        self._apply_graph_pens()

        set_windows_autostart(APP_NAME, self.settings.autostart)


    def _build_simple_page(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(6)

        l.addStretch(1)

        self.lbl_mbps = QLabel("0.0 Mbps")
        self.lbl_mbps.setObjectName("mbps")

        self.lbl_slash = QLabel(" / ")
        self.lbl_slash.setObjectName("slash")

        self.lbl_ping = QLabel("— ms")
        self.lbl_ping.setObjectName("ping")

        center = QWidget()
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addStretch(1)
        cl.addWidget(self.lbl_mbps)
        cl.addWidget(self.lbl_slash)
        cl.addWidget(self.lbl_ping)
        cl.addStretch(1)

        l.addWidget(center)
        l.addStretch(1)

        self.lbl_up = QLabel("↑ 0.00 MB")
        self.lbl_down = QLabel("↓ 0.00 MB")
        self.lbl_up.setObjectName("up")
        self.lbl_down.setObjectName("down")

        bottom = QWidget()
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(18, 0, 18, 14)
        bl.setSpacing(12)
        bl.addStretch(1)
        bl.addWidget(self.lbl_up)
        bl.addWidget(self.lbl_down)
        bl.addStretch(1)

        l.addWidget(bottom)
        return page

    def _build_adv_page(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(12, 8, 12, 12)
        l.setSpacing(10)

        self.lbl_adv_line1 = QLabel("");
        self.lbl_adv_line1.setObjectName("advinfo")
        self.lbl_adv_line2 = QLabel("");
        self.lbl_adv_line2.setObjectName("advinfo")
        self.lbl_adv_line3 = QLabel("");
        self.lbl_adv_line3.setObjectName("advinfo")
        l.addWidget(self.lbl_adv_line1)
        l.addWidget(self.lbl_adv_line2)
        l.addWidget(self.lbl_adv_line3)

        pg.setConfigOptions(antialias=True)

        axis_time_mbps = pg.DateAxisItem(orientation="bottom")
        axis_time_ping = pg.DateAxisItem(orientation="bottom")

        self.plot_mbps = pg.PlotWidget(axisItems={"bottom": axis_time_mbps})
        self.plot_ping = pg.PlotWidget(axisItems={"bottom": axis_time_ping})

        for p in (self.plot_mbps, self.plot_ping):
            p.setBackground((0, 0, 0, 0))
            p.showGrid(x=True, y=True, alpha=0.25)
            p.getAxis("bottom").setPen(pg.mkPen((200, 200, 200, 120)))
            p.getAxis("left").setPen(pg.mkPen((200, 200, 200, 120)))
            p.getAxis("bottom").setTextPen(pg.mkPen((220, 220, 220)))
            p.getAxis("left").setTextPen(pg.mkPen((220, 220, 220)))
            p.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            p.setMinimumHeight(190)

        self.plot_mbps.setTitle("Скорость (Total Mbps)", color="#EDEDED", size="12pt")
        self.plot_ping.setTitle("Ping (ms)", color="#EDEDED", size="12pt")
        self.plot_mbps.setLabel("left", "Mbps")
        self.plot_ping.setLabel("left", "ms")

        self.mbps_g = self.plot_mbps.plot([], [], pen=pg.mkPen(GREEN, width=self.settings.line_width))
        self.mbps_y = self.plot_mbps.plot([], [], pen=pg.mkPen(YELLOW, width=self.settings.line_width))
        self.mbps_r = self.plot_mbps.plot([], [], pen=pg.mkPen(RED, width=self.settings.line_width))
        self.mbps_c = self.plot_mbps.plot([], [], pen=pg.mkPen(self.settings.graph_custom_color,
                                                               width=self.settings.line_width))

        self.ping_g = self.plot_ping.plot([], [], pen=pg.mkPen(GREEN, width=self.settings.line_width))
        self.ping_y = self.plot_ping.plot([], [], pen=pg.mkPen(YELLOW, width=self.settings.line_width))
        self.ping_r = self.plot_ping.plot([], [], pen=pg.mkPen(RED, width=self.settings.line_width))
        self.ping_c = self.plot_ping.plot([], [], pen=pg.mkPen(self.settings.graph_custom_color,
                                                               width=self.settings.line_width))

        l.addWidget(self.plot_mbps, 2)
        l.addWidget(self.plot_ping, 2)

        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(["Адаптер", "Total Mbps", "Down Mbps", "Up Mbps", "Sent/Recv MB"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 5):
            self.tbl.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.tbl.setObjectName("advtable")
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setSelectionMode(QTableWidget.NoSelection)
        self.tbl.setFocusPolicy(Qt.NoFocus)
        self.tbl.setMinimumHeight(180)
        self.tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        l.addWidget(self.tbl, 2)

        return page

    def _apply_styles(self):
        self.btn_gear.setStyleSheet("""
            QToolButton {
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 10px;
                padding: 6px;
            }
            QToolButton:hover { background: rgba(255,255,255,0.14); }
            QToolButton:pressed { background: rgba(0,0,0,0.20); }
        """)
        self._apply_root_style()

    def _apply_root_style(self):
        alpha = self.settings.window_opacity / 100.0
        base = 0.30 if self.settings.transparent_mode else 0.55
        a = min(0.85, base + alpha)

        self.root.setStyleSheet(f"""
            QWidget#root {{
                background: rgba(0,0,0,{a});
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 18px;
            }}
            QLabel#connected {{
                color: rgba(255,255,255,0.92);
                font-size: 14px;
                font-weight: 600;
            }}
            QLabel#mbps, QLabel#ping, QLabel#slash {{
                font-size: 34px;
                font-weight: 800;
                letter-spacing: 0.5px;
            }}
            QLabel#slash {{ color: rgba(255,255,255,0.75); }}
            QLabel#up {{ color: {GREEN}; font-size: 14px; font-weight: 700; }}
            QLabel#down {{ color: {BLUE}; font-size: 14px; font-weight: 700; }}
            QLabel#advinfo {{ color: rgba(255,255,255,0.86); font-size: 13px; font-weight: 600; }}
            QTableWidget#advtable {{
                background: rgba(0,0,0,0.20);
                color: rgba(255,255,255,0.90);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 12px;
                gridline-color: rgba(255,255,255,0.08);
            }}
            QHeaderView::section {{
                background: rgba(0,0,0,0.30);
                color: rgba(255,255,255,0.90);
                padding: 6px;
                border: none;
            }}
        """)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bg.setGeometry(0, 0, self.width(), self.height())
        self.root.setGeometry(0, 0, self.width(), self.height())
        self._schedule_save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save_geometry()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def _update_background(self):
        if self.settings.use_builtin_background and self.settings.builtin_background_name:
            p = backgrounds_dir() / self.settings.builtin_background_name
            if p.exists():
                pm = safe_pixmap(p)
                if pm is not None:
                    self.bg.setPixmap(pm)
                    return

        if self.settings.background_path:
            p = Path(self.settings.background_path)
            if p.exists():
                pm = safe_pixmap(p)
                if pm is not None:
                    self.bg.setPixmap(pm)
                    return

        pm = QPixmap(self.size())
        pm.fill(Qt.black)
        self.bg.setPixmap(pm)

    def _apply_blur_for_mode(self):
        want = self.settings.blur_advanced if self.settings.mode == "advanced" else self.settings.blur_simple
        if want and self.settings.blur_radius > 0:
            self.blur_effect.setBlurRadius(self.settings.blur_radius)
            self.bg.setGraphicsEffect(self.blur_effect)
        else:
            self.bg.setGraphicsEffect(None)

    def _apply_mode_and_geometry(self):
        if self.settings.mode == "advanced":
            self.stack.setCurrentIndex(1)
            self.resize(self.settings.adv_w, self.settings.adv_h)
        else:
            self.stack.setCurrentIndex(0)
            self.resize(self.settings.simple_w, self.settings.simple_h)

        if self.settings.remember_geometry and self.settings.window_x >= 0 and self.settings.window_y >= 0:
            self.move(self.settings.window_x, self.settings.window_y)

    def _schedule_save_geometry(self):
        if not self.settings.remember_geometry:
            return
        self._save_geom_timer.start(250)

    def _persist_geometry(self):
        if not self.settings.remember_geometry:
            return
        pos = self.pos()
        self.settings.window_x = int(pos.x())
        self.settings.window_y = int(pos.y())
        save_settings(self.settings)

    def _resolve_adapter(self, value: str) -> str:

        v = (value or "active")
        if v == "active":
            return self.active_adapter

        if v not in psutil.net_if_stats():
            return self.active_adapter
        return v


    def _apply_graph_follow(self):
        if hasattr(self, "plot_ping") and hasattr(self, "plot_mbps"):
            try:
                if self.settings.follow_graph:
                    self.plot_ping.setXLink(self.plot_mbps)
                else:
                    self.plot_ping.setXLink(None)
            except Exception:
                pass

    def _apply_graph_pens(self):
        lw = self.settings.line_width
        if hasattr(self, "mbps_g"):
            self.mbps_g.setPen(pg.mkPen(GREEN, width=lw))
            self.mbps_y.setPen(pg.mkPen(YELLOW, width=lw))
            self.mbps_r.setPen(pg.mkPen(RED, width=lw))
            self.mbps_c.setPen(pg.mkPen(self.settings.graph_custom_color, width=lw))

            self.ping_g.setPen(pg.mkPen(GREEN, width=lw))
            self.ping_y.setPen(pg.mkPen(YELLOW, width=lw))
            self.ping_r.setPen(pg.mkPen(RED, width=lw))
            self.ping_c.setPen(pg.mkPen(self.settings.graph_custom_color, width=lw))

    def _setup_tray(self):
        if self.tray:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None
        if self.tray_update_timer:
            self.tray_update_timer.stop()
            self.tray_update_timer.deleteLater()
            self.tray_update_timer = None

        if not self.settings.tray_enabled:
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(tray_icon, self)

        menu = QMenu()
        act_show = QAction("Открыть", self)
        act_hide = QAction("Скрыть", self)
        act_quit = QAction("Выход", self)
        act_show.triggered.connect(self.show_normal)
        act_hide.triggered.connect(self.hide)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_show)
        menu.addAction(act_hide)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        self.tray_update_timer = QTimer(self)
        self.tray_update_timer.timeout.connect(self._update_tray_tooltip)
        self.tray_update_timer.start(1000)
        self._update_tray_tooltip()

    def _update_tray_tooltip(self):
        ping = self.last_ping_ms
        ping_str = "—" if ping is None else f"{ping} ms"

        simple_nic = self._resolve_adapter(self.settings.simple_adapter)
        graph_nic = self._resolve_adapter(self.settings.graph_adapter)

        tip = (
            f"{APP_NAME} v{APP_VERSION}\n"
            f"Active: {self.active_adapter}\n"
            f"Simple: {simple_nic}  |  Graph: {graph_nic}\n"
            f"Simple Total: {self.last_mbps_simple_total:.2f} Mbps (D {self.last_mbps_simple_down:.2f} / U {self.last_mbps_simple_up:.2f})\n"
            f"Ping: {ping_str} -> {self.settings.ping_host}\n"
            f"Requests: {self.ping_sent} (ok {self.ping_ok} / fail {self.ping_fail})\n"
            f"Sent: {self.total_sent_mb:.2f} MB | Recv: {self.total_recv_mb:.2f} MB"
        )
        if self.tray:
            self.tray.setToolTip(tip)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.settings.tray_click_popup and self.tray:
                self._update_tray_tooltip()
                self.tray.showMessage(APP_NAME, self.tray.toolTip(), QSystemTrayIcon.Information, 2500)
            if self.isVisible():
                self.hide()
            else:
                self.show_normal()

    def show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()


    def tick_stats(self):
        # refresh active adapter
        new_adapter = pick_active_adapter_name()
        if new_adapter != self.active_adapter:
            self.active_adapter = new_adapter
            self.lbl_connected.setText(f"Подключено — {self.active_adapter}")


        pernic = psutil.net_io_counters(pernic=True)

        tmono = time.monotonic()
        twall = time.time()

        for nic, c in pernic.items():
            sent, recv = c.bytes_sent, c.bytes_recv

            if nic not in self.nic_last:
                self.nic_last[nic] = (sent, recv, tmono)
                self.nic_speed_total_mbps[nic] = 0.0
                self.nic_speed_down_mbps[nic] = 0.0
                self.nic_speed_up_mbps[nic] = 0.0
                self.nic_sent_mb[nic] = sent / (1024 * 1024)
                self.nic_recv_mb[nic] = recv / (1024 * 1024)
            else:
                psent, precv, ptm = self.nic_last[nic]
                dt = max(0.050, tmono - ptm)
                d_sent = max(0, sent - psent)
                d_recv = max(0, recv - precv)

                up_mbps = (d_sent * 8.0) / dt / 1_000_000.0
                down_mbps = (d_recv * 8.0) / dt / 1_000_000.0
                total_mbps = up_mbps + down_mbps

                self.nic_speed_up_mbps[nic] = float(max(0.0, up_mbps))
                self.nic_speed_down_mbps[nic] = float(max(0.0, down_mbps))
                self.nic_speed_total_mbps[nic] = float(max(0.0, total_mbps))

                self.nic_sent_mb[nic] = sent / (1024 * 1024)
                self.nic_recv_mb[nic] = recv / (1024 * 1024)
                self.nic_last[nic] = (sent, recv, tmono)


        io = psutil.net_io_counters()
        self.total_sent_mb = io.bytes_sent / (1024 * 1024)
        self.total_recv_mb = io.bytes_recv / (1024 * 1024)


        simple_nic = self._resolve_adapter(self.settings.simple_adapter)
        self.last_mbps_simple_total = float(self.nic_speed_total_mbps.get(simple_nic, 0.0))
        self.last_mbps_simple_down = float(self.nic_speed_down_mbps.get(simple_nic, 0.0))
        self.last_mbps_simple_up = float(self.nic_speed_up_mbps.get(simple_nic, 0.0))

        self.simple_hist_total.append(self.last_mbps_simple_total)
        self.simple_hist_down.append(self.last_mbps_simple_down)
        self.simple_hist_up.append(self.last_mbps_simple_up)


        graph_nic = self._resolve_adapter(self.settings.graph_adapter)
        self.last_mbps_graph_total = float(self.nic_speed_total_mbps.get(graph_nic, 0.0))


        self.t_hist.append(twall)
        self.mbps_hist.append(self.last_mbps_graph_total)
        self.ping_hist.append(float(self.last_ping_ms) if self.last_ping_ms is not None else float("nan"))

        self._update_simple_ui()
        if self.settings.mode == "advanced":
            self._update_advanced_ui()

    def request_ping(self):
        self.ping_sent += 1
        task = PingTask(self.settings.ping_host)
        task.signals.done.connect(self.on_ping_done)
        self.thread_pool.start(task)

    def on_ping_done(self, ms):
        if isinstance(ms, int):
            self.last_ping_ms = ms
            self.ping_ok += 1
        else:
            self.last_ping_ms = None
            self.ping_fail += 1

        self._update_simple_ui()
        if self.settings.mode == "advanced":
            self._update_advanced_ui()


    def _format_rate(self, mbps: float) -> str:

        if mbps < 1.0:
            return f"{mbps * 1000:.0f} Kbps"
        return f"{mbps:.1f} Mbps"

    def _update_simple_ui(self):
        ping = self.last_ping_ms


        avg_total = sum(self.simple_hist_total) / max(1, len(self.simple_hist_total))
        avg_down = sum(self.simple_hist_down) / max(1, len(self.simple_hist_down))
        avg_up = sum(self.simple_hist_up) / max(1, len(self.simple_hist_up))


        self.lbl_mbps.setText(self._format_rate(avg_total))
        self.lbl_ping.setText(f"{('—' if ping is None else ping)} ms")


        c_mbps = quality_color(avg_total, self.settings.good_mbps, self.settings.ok_mbps, invert=False)
        c_ping = quality_color(ping, self.settings.good_ping_ms, self.settings.ok_ping_ms, invert=True)

        self.lbl_mbps.setStyleSheet(f"color:{c_mbps}; font-size:34px; font-weight:800; letter-spacing:0.5px;")
        self.lbl_ping.setStyleSheet(f"color:{c_ping}; font-size:34px; font-weight:800; letter-spacing:0.5px;")


        self.lbl_up.setText(f"↑ {self.total_sent_mb:.2f} MB")
        self.lbl_down.setText(f"↓ {self.total_recv_mb:.2f} MB")

    def _update_advanced_ui(self):
        ping_str = "—" if self.last_ping_ms is None else f"{self.last_ping_ms} ms"
        simple_nic = self._resolve_adapter(self.settings.simple_adapter)
        graph_nic = self._resolve_adapter(self.settings.graph_adapter)

        self.lbl_adv_line1.setText(
            f"Active: {self.active_adapter}   |   Simple: {simple_nic}   |   Graph: {graph_nic}   |   Target: {self.settings.ping_host}")
        self.lbl_adv_line2.setText(f"Graph Total: {self.last_mbps_graph_total:.2f} Mbps   |   Ping: {ping_str}")
        self.lbl_adv_line3.setText(
            f"Requests: {self.ping_sent} (ok {self.ping_ok} / fail {self.ping_fail})   |   Sent {self.total_sent_mb:.2f} MB   Recv {self.total_recv_mb:.2f} MB")

        xs = list(self.t_hist)
        mbps_ys = list(self.mbps_hist)
        ping_ys = list(self.ping_hist)


        if self.settings.graph_color_mode == "custom":
            self.mbps_c.setData(xs, mbps_ys)
            self.ping_c.setData(xs, ping_ys)

            nan = float("nan")
            self.mbps_g.setData(xs, [nan] * len(xs));
            self.mbps_y.setData(xs, [nan] * len(xs));
            self.mbps_r.setData(xs, [nan] * len(xs))
            self.ping_g.setData(xs, [nan] * len(xs));
            self.ping_y.setData(xs, [nan] * len(xs));
            self.ping_r.setData(xs, [nan] * len(xs))
        else:
            (xg, yg), (xy, yy), (xr, yr) = split_series_by_quality(xs, mbps_ys, self.settings.good_mbps,
                                                                   self.settings.ok_mbps, invert=False)
            self.mbps_g.setData(xg, yg)
            self.mbps_y.setData(xy, yy)
            self.mbps_r.setData(xr, yr)
            self.mbps_c.setData([], [])

            (xg2, yg2), (xy2, yy2), (xr2, yr2) = split_series_by_quality(xs, ping_ys, self.settings.good_ping_ms,
                                                                         self.settings.ok_ping_ms, invert=True)
            self.ping_g.setData(xg2, yg2)
            self.ping_y.setData(xy2, yy2)
            self.ping_r.setData(xr2, yr2)
            self.ping_c.setData([], [])

        selected = self.settings.monitored_adapters or []
        if not selected:
            selected = [self.active_adapter]

        rows = []
        for nic in selected:
            if nic in self.nic_speed_total_mbps:
                total = self.nic_speed_total_mbps.get(nic, 0.0)
                down = self.nic_speed_down_mbps.get(nic, 0.0)
                up = self.nic_speed_up_mbps.get(nic, 0.0)
                s_mb = self.nic_sent_mb.get(nic, 0.0)
                r_mb = self.nic_recv_mb.get(nic, 0.0)
                rows.append((nic, total, down, up, f"{s_mb:.2f}/{r_mb:.2f}"))

        self.tbl.setRowCount(len(rows))
        for r, (nic, total, down, up, sr) in enumerate(rows):
            self.tbl.setItem(r, 0, QTableWidgetItem(nic))
            self.tbl.setItem(r, 1, QTableWidgetItem(f"{total:.2f}"))
            self.tbl.setItem(r, 2, QTableWidgetItem(f"{down:.2f}"))
            self.tbl.setItem(r, 3, QTableWidgetItem(f"{up:.2f}"))
            self.tbl.setItem(r, 4, QTableWidgetItem(sr))

    def open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_to_settings()

            if self.settings.remember_geometry:
                pos = self.pos()
                self.settings.window_x = int(pos.x())
                self.settings.window_y = int(pos.y())

            save_settings(self.settings)
            set_windows_autostart(APP_NAME, self.settings.autostart)

            self.stats_timer.stop()
            self.stats_timer.start(self.settings.stats_refresh_ms)

            self.ping_timer.stop()
            self.ping_timer.start(self.settings.ping_refresh_ms)

            self._apply_root_style()
            self._update_background()
            self._apply_mode_and_geometry()
            self._apply_blur_for_mode()
            self._apply_graph_follow()
            self._apply_graph_pens()

            self._setup_tray()

    def closeEvent(self, event):
        if self.settings.tray_enabled and self.tray:
            event.ignore()
            self.hide()
        else:
            self._persist_geometry()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    w = NetPulseWindow()
    w.show_normal()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
