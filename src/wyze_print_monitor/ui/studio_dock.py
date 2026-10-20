"""Live view + camera controls embedded inside eufyMake Studio's Device tab.

Two panels are parented into Studio's own window tree (Qt foreign-window
parenting) and kept exactly on top of Studio's "Monitor" card (which can't
show a Wyze feed) and its empty "Others" card:

* **Monitor** — the live RTSP picture, a header with stream/recording/
  timelapse chips, and a capture toolbar (snapshot, record, timelapse,
  folders, fullscreen, full window, settings).
* **Camera** (in place of "Others") — Wyze connection, power/restart,
  siren/spotlight, motion/notifications and device info.

The panels are remote controls for :class:`MainWindow`: every button clicks
the matching main-window widget and the panels mirror its state on a timer.
All behavior (confirmations, error rollbacks, state reads) therefore stays in
one place. Studio's own Control, Progress and printer list are untouched.

Being children of Studio, the panels move, resize and minimize with it and
vanish on the Slice tab by themselves. They only show while the configured
printer (Settings → "Printer with camera") is selected in "My Printer".
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QPixmap, QWindow
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import studio_win32 as win
from .adjust_panel import ImageAdjustPanel
from .icons import (
    ICON_ADJUST,
    ICON_CAMERA,
    ICON_FOLDER,
    ICON_FULLSCREEN,
    ICON_RECORD,
    ICON_SETTINGS,
    ICON_TIMER,
    ICON_WINDOW,
    tool_button,
)
from .styles import (
    APP_BG,
    CARD,
    DIVIDER,
    GREEN,
    GREEN_BTN,
    GREEN_BTN_HOVER,
    RED,
    SELECTED,
    TEXT,
    TEXT_DIM,
    VIDEO_BG,
)

TICK_MS = 200
SEARCH_EVERY_S = 1.5   # how often to look for Studio while it isn't found
RELOCATE_EVERY_S = 3.0  # re-find printer rows (Studio rebuilds them on refresh)
HOLD_LAST_FRAME_S = 5.0  # keep the last picture through a reconnect this short
CARDS_HIDDEN_GRACE_S = 1.0  # Studio's refresh blinks are far shorter than this


# The panel's own sheet beats the app-wide DARK_QSS. Within it, equal
# specificity resolves by order: the catch-all QWidget rule comes first so
# every more specific rule below overrides it.
DOCK_QSS = f"""
QWidget {{
    background: transparent; color: {TEXT};
    font-family: "Segoe UI", sans-serif; font-size: 13px;
}}
QWidget#dockPanel {{ background: {CARD}; }}
QWidget#dockHeader {{ background: {CARD}; border-bottom: 1px solid {DIVIDER}; }}
QLabel#dockTitle {{ font-size: 15px; color: {TEXT}; }}
QLabel#dockVideo {{ background: {VIDEO_BG}; color: {TEXT_DIM}; font-size: 14px; }}
QWidget#dockToolbar {{ background: {CARD}; border-top: 1px solid {DIVIDER}; }}
QLabel#dockStatus {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#chip {{
    border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 600;
}}
QLabel#dim {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#section {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#camName {{ font-size: 14px; font-weight: 600; }}

QToolButton {{
    border: none; border-radius: 4px; padding: 3px 7px; color: {TEXT};
}}
QToolButton:hover {{ background: #34363a; }}
QToolButton:checked {{ background: {SELECTED}; color: {GREEN}; }}
QToolButton:disabled {{ color: #5d6066; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QPushButton {{
    background: {GREEN_BTN}; color: {GREEN}; border: none; border-radius: 3px;
    padding: 5px 10px; min-height: 18px;
}}
QPushButton:hover {{ background: {GREEN_BTN_HOVER}; }}
QPushButton:checked {{ background: {GREEN}; color: #10240f; }}
QPushButton:disabled {{ background: #2f3033; color: #63666b; }}
QPushButton#danger {{ background: #3a2626; color: {RED}; }}
QPushButton#danger:hover {{ background: #4a2c2c; }}
QPushButton#danger:checked {{ background: {RED}; color: #2a0f0f; }}
QPushButton#danger:disabled {{ background: #2f3033; color: #63666b; }}
QPushButton#accent {{ background: {GREEN}; color: #10240f; font-weight: 600; padding: 3px 10px; }}
QPushButton#accent:hover {{ background: #74dc73; }}
QPushButton#plain {{ background: #34363a; color: {TEXT}; }}
QPushButton#plain:hover {{ background: #3d4044; }}
QPushButton#plain:checked {{ background: {SELECTED}; color: {GREEN}; }}
QPushButton#plain:disabled {{ background: #2f3033; color: #63666b; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid #5d6066; background: {APP_BG};
}}
QCheckBox::indicator:checked {{ background: {GREEN}; border-color: {GREEN}; }}
QCheckBox:disabled {{ color: #63666b; }}

QComboBox {{
    background: {APP_BG}; border: 1px solid {DIVIDER}; border-radius: 3px; padding: 2px 6px;
}}
QMenu {{ background: {CARD}; color: {TEXT}; border: 1px solid {DIVIDER}; }}
QMenu::item:selected {{ background: {SELECTED}; }}
"""

def _chip(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("chip")
    label.hide()
    return label


def _set_chip(label: QLabel, text: str, bg: str, fg: str = "#ffffff") -> None:
    if not text:
        if label.isVisibleTo(label.parentWidget()):
            label.hide()
        return
    label.setText(text)
    # Re-polishing a stylesheet is costly; this runs every tick, so only
    # restyle when the color actually changes.
    if label.property("chipColors") != f"{bg}|{fg}":
        label.setProperty("chipColors", f"{bg}|{fg}")
        label.setStyleSheet(f"QLabel#chip {{ background: {bg}; color: {fg}; }}")
    if not label.isVisibleTo(label.parentWidget()):
        label.show()


def _tool(glyph: str, text: str, tip: str, checkable: bool = False) -> QToolButton:
    return tool_button(glyph, text, tip, checkable)


def _header(title: str) -> tuple[QWidget, QHBoxLayout]:
    header = QWidget()
    header.setObjectName("dockHeader")
    header.setAttribute(Qt.WA_StyledBackground, True)
    header.setFixedHeight(29)
    row = QHBoxLayout(header)
    row.setContentsMargins(10, 0, 8, 0)
    row.setSpacing(6)
    label = QLabel(title)
    label.setObjectName("dockTitle")
    row.addWidget(label)
    row.addStretch(1)
    return header, row


class _Panel(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint)
        self.setObjectName("dockPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setStyleSheet(DOCK_QSS)


class MonitorPanel(_Panel):
    """Replaces Studio's Monitor card: live picture + capture toolbar."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header, row = _header("Monitor")
        self.rec_chip = _chip()
        self.timelapse_chip = _chip()
        self.info_label = QLabel()
        self.info_label.setObjectName("dim")
        self.state_chip = _chip()
        for widget in (self.rec_chip, self.timelapse_chip, self.info_label, self.state_chip):
            row.addWidget(widget)
        layout.addWidget(header)

        self.video = QLabel()
        self.video.setObjectName("dockVideo")
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setMinimumSize(160, 90)
        self.video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.video, 1)

        bar = QWidget()
        bar.setObjectName("dockToolbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setFixedHeight(36)
        tools = QHBoxLayout(bar)
        tools.setContentsMargins(6, 3, 6, 3)
        tools.setSpacing(2)
        self.snapshot_btn = _tool(ICON_CAMERA, "Snapshot", "Save a PNG of the current frame")
        self.record_btn = _tool(ICON_RECORD, "Record", "Record an MP4 clip", checkable=True)
        self.timelapse_btn = _tool(ICON_TIMER, "Timelapse", "Capture a print timelapse", checkable=True)
        self.adjust_btn = _tool(ICON_ADJUST, "Adjust", "Brightness, exposure, zoom, rotate…")
        self.folder_btn = _tool(ICON_FOLDER, "", "Open snapshot / video folder")
        self.folder_btn.setPopupMode(QToolButton.InstantPopup)
        self.status = QLabel()
        self.status.setObjectName("dockStatus")
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.update_btn = QPushButton("Update")
        self.update_btn.setObjectName("accent")
        self.update_btn.hide()
        self.fullscreen_btn = _tool(ICON_FULLSCREEN, "", "Fullscreen (Esc to exit)")
        self.window_btn = _tool(ICON_WINDOW, "", "Open the full Wyze Print Monitor window")
        self.settings_btn = _tool(ICON_SETTINGS, "", "Settings")
        for widget in (self.snapshot_btn, self.record_btn, self.timelapse_btn, self.adjust_btn, self.folder_btn):
            tools.addWidget(widget)
        tools.addSpacing(8)
        tools.addWidget(self.status, 1)
        for widget in (self.update_btn, self.fullscreen_btn, self.window_btn, self.settings_btn):
            tools.addWidget(widget)
        layout.addWidget(bar)


class CameraPanel(_Panel):
    """Replaces Studio's empty "Others" card: the Wyze camera controls."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header, row = _header("Wyze Cam")
        self.conn_chip = _chip()
        self.settings_btn = _tool(ICON_SETTINGS, "", "Settings")
        row.addWidget(self.conn_chip)
        row.addWidget(self.settings_btn)
        layout.addWidget(header)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        self.name_label = QLabel("Wyze camera")
        self.name_label.setObjectName("camName")
        self.camera_combo = QComboBox()
        self.camera_combo.hide()
        self.details_label = QLabel("Not connected")
        self.details_label.setObjectName("dim")
        self.details_label.setWordWrap(True)
        grid.addWidget(self.name_label, 0, 0, 1, 3)
        grid.addWidget(self.camera_combo, 0, 0, 1, 3)
        grid.addWidget(self.details_label, 1, 0, 1, 3)

        grid.addWidget(self._section("POWER"), 2, 0, 1, 3)
        self.power_on_btn = QPushButton("Turn on")
        self.power_off_btn = QPushButton("Turn off")
        self.restart_btn = QPushButton("Restart")
        grid.addWidget(self.power_on_btn, 3, 0)
        grid.addWidget(self.power_off_btn, 3, 1)
        grid.addWidget(self.restart_btn, 3, 2)

        grid.addWidget(self._section("SIREN & SPOTLIGHT"), 4, 0, 1, 3)
        self.siren_btn = QPushButton("Siren")
        self.siren_btn.setObjectName("danger")
        self.siren_btn.setCheckable(True)
        self.spotlight_btn = QPushButton("Spotlight")
        self.spotlight_btn.setCheckable(True)
        grid.addWidget(self.siren_btn, 5, 0, 1, 1)
        grid.addWidget(self.spotlight_btn, 5, 1, 1, 2)

        grid.addWidget(self._section("DETECTION"), 6, 0, 1, 3)
        self.motion_check = QCheckBox("Motion detection")
        self.notify_check = QCheckBox("Push notifications")
        grid.addWidget(self.motion_check, 7, 0, 1, 2)
        grid.addWidget(self.notify_check, 8, 0, 1, 2)

        conn = QHBoxLayout()
        conn.setSpacing(6)
        self.conn_label = QLabel()
        self.conn_label.setObjectName("dim")
        self.conn_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.connect_btn = QPushButton("Connect")
        self.refresh_btn = QPushButton("Refresh")
        conn.addWidget(self.conn_label, 1)
        conn.addWidget(self.connect_btn)
        conn.addWidget(self.refresh_btn)
        grid.addLayout(conn, 9, 0, 1, 3)
        grid.setRowStretch(10, 1)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        layout.addWidget(body, 1)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label


class AdjustPopup(QWidget):
    """The picture adjustments, popping up over the docked Monitor."""

    def __init__(self, main) -> None:
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("dockPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(DOCK_QSS + f"QWidget#dockPanel {{ border: 1px solid {DIVIDER}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = ImageAdjustPanel(main)
        layout.addWidget(self.panel)
        self.setFixedWidth(340)

    def show_above(self, anchor: QWidget) -> None:
        """Open just above ``anchor`` (a toolbar button), kept on screen."""
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, 0)) - QPoint(0, self.height() + 6)
        screen = anchor.screen().availableGeometry()
        pos.setX(min(max(pos.x(), screen.left()), screen.right() - self.width()))
        pos.setY(max(pos.y(), screen.top()))
        self.move(pos)
        self.show()


def _mirror_button(dock: QAbstractButton, main: QAbstractButton) -> None:
    """Clicking the dock button clicks the main-window one (same handlers)."""
    def forward() -> None:
        if dock.isCheckable():
            # Undo the dock's own toggle; the next sync copies main's state,
            # which a failed command may roll back.
            dock.blockSignals(True)
            dock.setChecked(not dock.isChecked())
            dock.blockSignals(False)
        main.click()

    dock.clicked.connect(forward)


def _sync_button(dock: QAbstractButton, main: QAbstractButton, text: str | None = None) -> None:
    if dock.isEnabled() != main.isEnabled():
        dock.setEnabled(main.isEnabled())
    if dock.isCheckable() and dock.isChecked() != main.isChecked():
        dock.blockSignals(True)
        dock.setChecked(main.isChecked())
        dock.blockSignals(False)
    wanted = main.text() if text is None else text
    if dock.text() != wanted:
        dock.setText(wanted)


class StudioDock(QObject):
    """Keeps the two panels attached to (and aligned with) eufyMake Studio."""

    def __init__(self, main) -> None:  # main: MainWindow (import cycle avoided)
        super().__init__(main)
        self.main = main
        self.monitor: MonitorPanel | None = None
        self.camera: CameraPanel | None = None
        self._foreign: list[QWindow] = []
        self._layout: win.StudioLayout | None = None
        self._last_search = 0.0
        self._last_relocate = 0.0
        # Is the configured printer selected in Studio? None = not read yet.
        self._printer_ok: bool | None = None
        self._printer_row = main.settings.dock_printer_row
        self._row_tick = 0
        self._placed: dict[int, tuple] = {}
        self._status_until = 0.0
        self._not_live_since: float | None = None
        self._cards_hidden_since: float | None = None
        self._adjust_popup: AdjustPopup | None = None

        main.status_message.connect(self._on_status)
        QApplication.instance().aboutToQuit.connect(self.detach)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if sys.platform == "win32":
            self._timer.start(TICK_MS)

    # ------------------------------------------------------------------ state
    @property
    def attached(self) -> bool:
        return self.monitor is not None

    def studio_running(self) -> bool:
        return win.find_studio() is not None

    # ------------------------------------------------------------------ tick
    def _tick(self) -> None:
        settings = self.main.settings
        # Closing the window only hides it while Studio is hosting our panels;
        # otherwise it quits as before.
        self.main.hide_on_close = settings.dock_in_studio and self._layout is not None
        if not settings.dock_in_studio:
            was_attached = self.attached
            self.detach()
            if was_attached:
                # Embedding was just switched off: the full window is now
                # the only place the live view lives, so bring it back.
                self.main.show_window()
            return
        if settings.dock_printer_row != self._printer_row:
            # A decision made for another printer row says nothing about this
            # one: re-check before showing anything.
            self._printer_row = settings.dock_printer_row
            self._printer_ok = None
        now = time.monotonic()
        layout = self._layout
        if layout is None or not all(
            win.is_window(h)
            for h in (layout.host, layout.content, layout.monitor_card, layout.others_card)
        ):
            self.detach()  # Studio closed or rebuilt its Device tab
            self._layout = None
            if now - self._last_search < SEARCH_EVERY_S:
                return
            self._last_search = now
            top = win.find_studio()
            layout = win.locate_layout(top) if top else None
            if layout is None:
                return
            self._layout = layout
            self._last_relocate = now
            self._printer_ok = None  # a (re)started Studio: read the selection afresh
        elif now - self._last_relocate > RELOCATE_EVERY_S or not all(
            win.is_window(r) for r in layout.printer_rows
        ):
            self._last_relocate = now
            fresh = win.locate_layout(layout.top)
            if fresh is not None and fresh.content == layout.content:
                layout.printer_rows = fresh.printer_rows

        if self.attached and not all(
            win.is_window(int(p.winId())) for p in (self.monitor, self.camera)
        ):
            self.detach()  # our children died with Studio's windows
            return

        cards_shown = win.is_visible(layout.monitor_card) and win.is_visible(layout.others_card)
        if cards_shown:
            self._cards_hidden_since = None
        elif self._cards_hidden_since is None:
            self._cards_hidden_since = now
        # Studio blinks its Device-tab content off for ~30-80 ms every few
        # seconds. Treating that as "left the tab" hid our panels until the
        # next tick and let Studio's own Monitor flash through. Only a
        # sustained hide counts (on the Slice tab the whole page is hidden,
        # which hides our panels with it anyway).
        cards_gone = (
            self._cards_hidden_since is not None
            and now - self._cards_hidden_since >= CARDS_HIDDEN_GRACE_S
        )
        on_device_tab = not win.is_minimized(layout.top) and not cards_gone
        if on_device_tab and cards_shown:
            # Sampling the screen is the slow part: every other tick is plenty
            # once we know the answer, but read every tick until we do.
            self._row_tick = (self._row_tick + 1) % 2
            if self._row_tick == 0 or self._printer_ok is None:
                selected = win.selected_row_index([win.row_color(r) for r in layout.printer_rows])
                self._printer_ok = win.camera_printer_selected(
                    selected, settings.dock_printer_row, self._printer_ok
                )
        # Only a confirmed match shows the panels; unknown stays hidden.
        want = on_device_tab and self._printer_ok is True
        if want and not self.attached:
            self._attach(layout)
        if not self.attached:
            return
        # The content area (our panels' lower sibling) and the cards must not
        # paint over the panels sitting above them.
        win.ensure_clips_siblings(layout.content)
        for panel, card in ((self.monitor, layout.monitor_card), (self.camera, layout.others_card)):
            win.ensure_clips_siblings(card)
            if want:
                self._align(panel, card, layout)
            if panel.isVisible() != want:
                panel.setVisible(want)
        if want:
            self._sync()

    def _align(self, panel: QWidget, card: int, layout: win.StudioLayout) -> None:
        hwnd = int(panel.winId())
        rect = win.rect_in_parent(card, layout.host)
        # Siblings of the content area: stay above it in z-order.
        needs_raise = not win.is_above(hwnd, layout.content)
        if needs_raise or self._placed.get(hwnd) != rect:
            win.place(hwnd, rect, raise_to_top=needs_raise)
            self._placed[hwnd] = rect

    # ------------------------------------------------------------------ attach / detach
    def _attach(self, layout: win.StudioLayout) -> None:
        self.monitor = MonitorPanel()
        self.camera = CameraPanel()
        self._wire()
        scale = win.dpi_scale(layout.host)
        win.ensure_clips_siblings(layout.content)
        for panel, card in ((self.monitor, layout.monitor_card), (self.camera, layout.others_card)):
            foreign = QWindow.fromWinId(layout.host)
            self._foreign.append(foreign)
            panel.winId()  # create the native window before reparenting it
            panel.windowHandle().setParent(foreign)
            x, y, w, h = win.rect_in_parent(card, layout.host)
            panel.setGeometry(round(x / scale), round(y / scale), round(w / scale), round(h / scale))
            panel.show()
            self._align(panel, card, layout)
        self.main.extra_video_labels.append(self.monitor.video)
        self._sync()

    def detach(self) -> None:
        """Remove our panels from Studio (or clean up after Studio closed)."""
        if not self.attached:
            return
        if self.monitor.video in self.main.extra_video_labels:
            self.main.extra_video_labels.remove(self.monitor.video)
        for panel in (self.monitor, self.camera):
            alive = win.is_window(int(panel.winId()))
            if alive:
                panel.hide()
                # Unparent before destroying so teardown never depends on
                # Studio's message loop. If Studio already closed, Windows
                # destroyed our child windows with it: leave them alone.
                handle = panel.windowHandle()
                if handle is not None:
                    handle.setParent(None)
            panel.deleteLater()
        # Queued after the panels, so each panel is gone before its foreign
        # parent wrapper is.
        for foreign in self._foreign:
            foreign.deleteLater()
        self._foreign.clear()
        self._placed.clear()
        self.monitor = self.camera = None
        if self._adjust_popup is not None:
            self._adjust_popup.hide()
            self._adjust_popup.deleteLater()
            self._adjust_popup = None

    # ------------------------------------------------------------------ wiring
    def _wire(self) -> None:
        m, mon, cam = self.main, self.monitor, self.camera
        _mirror_button(mon.snapshot_btn, m.snapshot_btn)
        _mirror_button(mon.record_btn, m.record_btn)
        _mirror_button(mon.timelapse_btn, m.timelapse_btn)
        mon.fullscreen_btn.clicked.connect(m._toggle_fullscreen)
        mon.window_btn.clicked.connect(m.show_window)
        mon.settings_btn.clicked.connect(m._open_settings)
        mon.adjust_btn.clicked.connect(self._show_adjust)
        mon.update_btn.clicked.connect(m.update_manager.install)
        cam.settings_btn.clicked.connect(m._open_settings)
        folders = QMenu(mon.folder_btn)
        folders.addAction("Open snapshot folder", lambda: m._open_folder(m.settings.resolved_snapshot_dir()))
        folders.addAction("Open video folder", lambda: m._open_folder(m.settings.resolved_video_dir()))
        mon.folder_btn.setMenu(folders)

        for dock_btn, main_btn in (
            (cam.power_on_btn, m.power_on_btn),
            (cam.power_off_btn, m.power_off_btn),
            (cam.restart_btn, m.restart_btn),
            (cam.siren_btn, m.siren_btn),
            (cam.spotlight_btn, m.spotlight_btn),
            (cam.motion_check, m.motion_check),
            (cam.notify_check, m.notify_check),
            (cam.connect_btn, m.connect_btn),
            (cam.refresh_btn, m.refresh_btn),
        ):
            _mirror_button(dock_btn, main_btn)
        cam.camera_combo.activated.connect(m.camera_list.setCurrentRow)

    def _show_adjust(self) -> None:
        if self.monitor is None:
            return
        if self._adjust_popup is None:
            self._adjust_popup = AdjustPopup(self.main)
        self._adjust_popup.show_above(self.monitor.adjust_btn)

    # ------------------------------------------------------------------ mirroring
    def _on_status(self, message: str, timeout: int) -> None:
        if self.monitor is None:
            return
        self.monitor.status.setText(message)
        self.monitor.status.setToolTip(message)
        self._status_until = time.monotonic() + (timeout / 1000 if timeout else 8.0)

    def _sync(self) -> None:
        m, mon, cam = self.main, self.monitor, self.camera
        if mon is None or cam is None:
            return

        # --- monitor header
        state = getattr(m, "_stream_state", "idle")
        chip_colors = {
            "live": ("● LIVE", "#2f7d3a"),
            "connecting": ("Connecting…", "#8a6d2f"),
            "reconnecting": ("Reconnecting…", "#8a6d2f"),
            "error": ("Error", "#8a2f2f"),
        }
        text, bg = chip_colors.get(state, ("Idle", "#3d4148"))
        _set_chip(mon.state_chip, text, bg)
        info = m.stream_info_label.text() if state == "live" else ""
        if mon.info_label.text() != info:
            mon.info_label.setText(info)
        if m._recorder is not None and m._rec_start is not None:
            elapsed = int(time.monotonic() - m._rec_start)
            _set_chip(mon.rec_chip, f"● REC {elapsed // 60:02d}:{elapsed % 60:02d}", "#a33a3a")
        else:
            _set_chip(mon.rec_chip, "", "")
        if m._timelapse is not None:
            _set_chip(mon.timelapse_chip, f"Timelapse · {m._timelapse.saved} frames", "#3a4f7a")
        elif m._compile_worker is not None:
            _set_chip(mon.timelapse_chip, "Compiling timelapse…", "#3a4f7a")
        else:
            _set_chip(mon.timelapse_chip, "", "")

        # --- picture placeholder while there's no live stream (live frames
        # are pushed straight into mon.video by MainWindow._on_frame)
        if state == "live":
            self._not_live_since = None
        elif self._not_live_since is None:
            self._not_live_since = time.monotonic()
        # A brief drop + reconnect shouldn't blank the picture: keep the last
        # frame up (the header chip already says "Reconnecting…") and only
        # fall back to the placeholder once the stream has really been gone.
        holding = (
            self._not_live_since is not None
            and time.monotonic() - self._not_live_since < HOLD_LAST_FRAME_S
            and not mon.video.pixmap().isNull()
        )
        if state != "live" and not holding:
            if not m.settings.rtsp_url:
                placeholder = "No signal — set your RTSP URL in Settings."
            elif state in ("connecting", "reconnecting"):
                placeholder = "Connecting to the camera…"
            else:
                placeholder = "Camera stream unavailable."
            if not mon.video.pixmap().isNull() or mon.video.text() != placeholder:
                mon.video.setPixmap(QPixmap())
                mon.video.setText(placeholder)

        # --- toolbar
        latest = m.update_manager.latest
        if (latest is not None) != mon.update_btn.isVisible():
            mon.update_btn.setVisible(latest is not None)
        if latest is not None and mon.update_btn.toolTip() != latest.version:
            mon.update_btn.setText(f"Update to {latest.version}")
            mon.update_btn.setToolTip(latest.version)
        _sync_button(mon.snapshot_btn, m.snapshot_btn, "Snapshot")
        _sync_button(mon.record_btn, m.record_btn, "Stop" if m.record_btn.isChecked() else "Record")
        _sync_button(mon.timelapse_btn, m.timelapse_btn, "Stop" if m.timelapse_btn.isChecked() else "Timelapse")
        if self._status_until and time.monotonic() > self._status_until:
            mon.status.setText("")
            self._status_until = 0.0

        # --- camera panel
        connected = m.controller.logged_in
        conn_text = m.conn_label.text()
        if connected and m._selected_camera() is not None:
            _set_chip(cam.conn_chip, "● Connected", "#2f7d3a")
        elif connected:
            _set_chip(cam.conn_chip, "Signed in", "#3d4148")
        else:
            _set_chip(cam.conn_chip, "Offline", "#3d4148")
        if cam.conn_label.text() != conn_text:
            cam.conn_label.setText(conn_text)
            cam.conn_label.setToolTip(conn_text)

        selected = m._selected_camera()
        name = selected.nickname if selected else (m.settings.camera_nickname or "Wyze camera")
        if cam.name_label.text() != name:
            cam.name_label.setText(name)
        details = (
            " · ".join(
                part
                for part in (
                    m.info_model.text(),
                    m.info_status.text(),
                    f"FW {m.info_firmware.text()}" if m.info_firmware.text() not in ("", "—") else "",
                    m.info_ip.text() if m.info_ip.text() != "—" else "",
                )
                if part and part != "—"
            )
            if selected
            else "Connect to Wyze to control the camera."
        )
        if cam.details_label.text() != details:
            cam.details_label.setText(details)
        self._sync_camera_combo()

        _sync_button(cam.power_on_btn, m.power_on_btn, "Turn on")
        _sync_button(cam.power_off_btn, m.power_off_btn, "Turn off")
        _sync_button(cam.restart_btn, m.restart_btn, "Restart")
        _sync_button(cam.siren_btn, m.siren_btn)
        _sync_button(cam.spotlight_btn, m.spotlight_btn)
        _sync_button(cam.motion_check, m.motion_check)
        _sync_button(cam.notify_check, m.notify_check)
        _sync_button(cam.connect_btn, m.connect_btn, "Reconnect" if connected else "Connect")
        _sync_button(cam.refresh_btn, m.refresh_btn, "Refresh")
        cam.refresh_btn.setVisible(connected)

    def _sync_camera_combo(self) -> None:
        cam, source = self.camera, self.main.camera_list
        names = [source.item(i).text().split("\n")[0] for i in range(source.count())]
        many = len(names) > 1
        cam.camera_combo.setVisible(many)
        cam.name_label.setVisible(not many)
        if not many:
            return
        current = [cam.camera_combo.itemText(i) for i in range(cam.camera_combo.count())]
        if current != names:
            cam.camera_combo.blockSignals(True)
            cam.camera_combo.clear()
            cam.camera_combo.addItems(names)
            cam.camera_combo.blockSignals(False)
        if cam.camera_combo.currentIndex() != source.currentRow():
            cam.camera_combo.blockSignals(True)
            cam.camera_combo.setCurrentIndex(source.currentRow())
            cam.camera_combo.blockSignals(False)
