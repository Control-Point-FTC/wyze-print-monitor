"""Live view + camera controls embedded inside eufyMake Studio's Device tab.

Two panels are parented into Studio's own window tree (Qt foreign-window
parenting) and kept exactly on top of Studio's "Monitor" card (which can't
show a Wyze feed) and its empty "Others" card:

* **Monitor** — a :class:`~.views.VideoView`: the live picture edge to edge,
  status chips over it, a floating toolbar, scroll-to-zoom and drag-to-pan.
* **Camera** (in place of "Others") — a :class:`~.views.CameraPanel`: toggle
  tiles, power, recent captures, quick picture controls, device details.

They're the same views the full window uses, bound to :class:`MainWindow`
by a :class:`~.binder.PanelBinder`, so all behavior stays in one place.
Studio's own Control, Progress and printer list are untouched.

Being children of Studio, the panels move, resize and minimize with it and
vanish on the Slice tab by themselves. They only show while the configured
printer (Settings → "Printer with camera") is selected in "My Printer".
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from .. import studio_win32 as win
from .binder import PanelBinder
from .views import VIEWS_QSS, CameraPanel, VideoView

TICK_MS = 200
SEARCH_EVERY_S = 1.5   # how often to look for Studio while it isn't found
RELOCATE_EVERY_S = 3.0  # re-find printer rows (Studio rebuilds them on refresh)
CARDS_HIDDEN_GRACE_S = 1.0  # Studio's refresh blinks are far shorter than this


class _Panel(QWidget):
    """A native top-level that gets parented into Studio, holding one view."""

    def __init__(self, view: QWidget) -> None:
        super().__init__(None, Qt.FramelessWindowHint)
        self.setObjectName("surface")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setStyleSheet(VIEWS_QSS)
        self.view = view
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view)


class StudioDock(QObject):
    """Keeps the two panels attached to (and aligned with) eufyMake Studio."""

    def __init__(self, main) -> None:  # main: MainWindow (import cycle avoided)
        super().__init__(main)
        self.main = main
        self.monitor: _Panel | None = None
        self.camera: _Panel | None = None
        self.binder: PanelBinder | None = None
        self._foreign: list[QWindow] = []
        self._layout: win.StudioLayout | None = None
        self._last_search = 0.0
        self._last_relocate = 0.0
        # Is the configured printer selected in Studio? None = not read yet.
        self._printer_ok: bool | None = None
        self._printer_row = main.settings.dock_printer_row
        self._row_tick = 0
        self._placed: dict[int, tuple] = {}
        self._cards_hidden_since: float | None = None

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
        self.monitor = _Panel(VideoView())
        self.camera = _Panel(CameraPanel())
        self.binder = PanelBinder(self.main, self.monitor.view, self.camera.view, parent=self)
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

    def detach(self) -> None:
        """Remove our panels from Studio (or clean up after Studio closed)."""
        if not self.attached:
            return
        if self.binder is not None:
            self.binder.close()
            self.binder.deleteLater()
            self.binder = None
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
