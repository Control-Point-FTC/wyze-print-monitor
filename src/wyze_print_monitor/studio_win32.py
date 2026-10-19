"""Find and track eufyMake Studio's Device tab (Windows only).

eufyMake Studio (a PrusaSlicer fork) is a wxWidgets app, so every panel on its
Device tab — the "My Printer" list, Monitor, Progress, Control, Others — is a
native child window. This module locates those windows by their header
labels so :mod:`ui.studio_dock` can place our own panels exactly over the
Monitor and Others cards.

Only read-only window queries plus two style/z-order tweaks are used; nothing
here sends messages into Studio, so a busy Studio can never stall our UI
thread through these calls. Everything degrades to "not found" off Windows.

The pure helpers at the top (no ctypes) hold the decision logic and are unit
tested; the Win32 calls below them are thin wrappers.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

STUDIO_TITLE_MARKERS = ("eufyMake Studio", "AnkerMake Studio")
MONITOR_LABEL = "Monitor"
OTHERS_LABEL = "Others"
PRINTER_LIST_LABEL = "My Printer"

Rect = tuple[int, int, int, int]  # left, top, width, height (physical px)


# --------------------------------------------------------------------- pure logic
def is_studio_title(title: str) -> bool:
    return any(marker in title for marker in STUDIO_TITLE_MARKERS)


def is_selected_row_color(rgb: tuple[int, int, int]) -> bool:
    """Studio paints the selected printer row green-tinted (≈ #354138) and the
    others neutral grey (≈ #292a2d). Green dominance tells them apart."""
    r, g, b = rgb
    return g - max(r, b) >= 6


def selected_row_index(colors: list[tuple[int, int, int] | None]) -> int | None:
    """Index of the one selected row, or None when unknown/ambiguous
    (a row was covered by another window, or no row looks selected)."""
    if not colors or any(c is None for c in colors):
        return None
    hits = [i for i, c in enumerate(colors) if c is not None and is_selected_row_color(c)]
    return hits[0] if len(hits) == 1 else None


def camera_printer_selected(selected: int | None, configured_row: int, previous: bool) -> bool:
    """Should the camera panels show? ``configured_row`` is 1-based, 0 = any
    printer. An unknown selection keeps the previous decision so a briefly
    covered sidebar doesn't make the panels flicker."""
    if configured_row <= 0:
        return True
    if selected is None:
        return previous
    return selected == configured_row - 1


def pick_printer_rows(
    candidates: list[tuple[int, Rect]], list_rect: Rect, header_bottom: int
) -> list[int]:
    """From visible windows inside the sidebar, keep the printer rows: nearly
    full sidebar width, short (a row, not the list), below the header. Sorted
    top to bottom."""
    _lx, _ly, lw, lh = list_rect
    rows = [
        (rect[1], hwnd)
        for hwnd, rect in candidates
        if rect[2] >= 0.8 * lw
        and 0.02 * lh <= rect[3] <= 0.2 * lh
        and rect[1] >= header_bottom
    ]
    return [hwnd for _top, hwnd in sorted(rows)]


@dataclass
class StudioLayout:
    """The Studio windows we care about (all HWNDs as ints)."""

    top: int
    content: int  # common parent of the Monitor and Others cards
    monitor_card: int
    others_card: int
    printer_rows: list[int] = field(default_factory=list)


# --------------------------------------------------------------------- Win32
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def _sig(fn, restype, *argtypes):
        fn.restype = restype
        fn.argtypes = list(argtypes)
        return fn

    _EnumWindows = _sig(_user32.EnumWindows, wt.BOOL, _ENUMPROC, wt.LPARAM)
    _EnumChildWindows = _sig(_user32.EnumChildWindows, wt.BOOL, wt.HWND, _ENUMPROC, wt.LPARAM)
    _GetWindowTextLengthW = _sig(_user32.GetWindowTextLengthW, ctypes.c_int, wt.HWND)
    _GetWindowTextW = _sig(_user32.GetWindowTextW, ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
    _IsWindowVisible = _sig(_user32.IsWindowVisible, wt.BOOL, wt.HWND)
    _IsWindow = _sig(_user32.IsWindow, wt.BOOL, wt.HWND)
    _IsIconic = _sig(_user32.IsIconic, wt.BOOL, wt.HWND)
    _GetParent = _sig(_user32.GetParent, wt.HWND, wt.HWND)
    _GetWindowRect = _sig(_user32.GetWindowRect, wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT))
    _ScreenToClient = _sig(_user32.ScreenToClient, wt.BOOL, wt.HWND, ctypes.POINTER(wt.POINT))
    _WindowFromPoint = _sig(_user32.WindowFromPoint, wt.HWND, wt.POINT)
    _GetAncestor = _sig(_user32.GetAncestor, wt.HWND, wt.HWND, wt.UINT)
    _GetWindowLongPtrW = _sig(_user32.GetWindowLongPtrW, ctypes.c_ssize_t, wt.HWND, ctypes.c_int)
    _SetWindowLongPtrW = _sig(_user32.SetWindowLongPtrW, ctypes.c_ssize_t, wt.HWND, ctypes.c_int, ctypes.c_ssize_t)
    _SetWindowPos = _sig(
        _user32.SetWindowPos, wt.BOOL, wt.HWND, wt.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT,
    )
    _GetWindow = _sig(_user32.GetWindow, wt.HWND, wt.HWND, wt.UINT)
    _GetDpiForWindow = _sig(_user32.GetDpiForWindow, wt.UINT, wt.HWND)
    _GetDC = _sig(_user32.GetDC, wt.HDC, wt.HWND)
    _ReleaseDC = _sig(_user32.ReleaseDC, ctypes.c_int, wt.HWND, wt.HDC)
    _GetPixel = _sig(_gdi32.GetPixel, wt.DWORD, wt.HDC, ctypes.c_int, ctypes.c_int)

    _GWL_STYLE = -16
    _WS_CLIPSIBLINGS = 0x04000000
    _GA_ROOT = 2
    _GW_HWNDPREV = 3
    _SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOZORDER, _SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
    _CLR_INVALID = 0xFFFFFFFF

    def _text(hwnd: int) -> str:
        n = _GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        _GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def window_rect(hwnd: int) -> Rect:
        r = wt.RECT()
        _GetWindowRect(hwnd, ctypes.byref(r))
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)

    def rect_in_parent(hwnd: int, parent: int) -> Rect:
        """``hwnd``'s rect in ``parent``'s client coordinates (physical px)."""
        x, y, w, h = window_rect(hwnd)
        p = wt.POINT(x, y)
        _ScreenToClient(parent, ctypes.byref(p))
        return (p.x, p.y, w, h)

    def is_window(hwnd: int | None) -> bool:
        return bool(hwnd) and bool(_IsWindow(hwnd))

    def is_visible(hwnd: int) -> bool:
        """True only if the window and all its ancestors are shown (so the
        Device tab's cards report False while Studio shows the Slice tab)."""
        return bool(_IsWindowVisible(hwnd))

    def is_minimized(hwnd: int) -> bool:
        return bool(_IsIconic(hwnd))

    def dpi_scale(hwnd: int) -> float:
        dpi = _GetDpiForWindow(hwnd)
        return dpi / 96.0 if dpi else 1.0

    def find_studio() -> int | None:
        found: list[int] = []

        def cb(hwnd, _lp):
            if _IsWindowVisible(hwnd) and is_studio_title(_text(hwnd)):
                found.append(hwnd)
                return False
            return True

        _EnumWindows(_ENUMPROC(cb), 0)
        return found[0] if found else None

    def _children(parent: int) -> list[int]:
        out: list[int] = []
        _EnumChildWindows(parent, _ENUMPROC(lambda h, _lp: out.append(h) or True), 0)
        return out

    def _ancestors(hwnd: int) -> list[int]:
        chain = []
        while hwnd:
            chain.append(hwnd)
            hwnd = _GetParent(hwnd)
        return chain

    def locate_layout(top: int) -> StudioLayout | None:
        """Find the Device tab's cards inside Studio's main window.

        The Monitor and Others cards are the children of the deepest window
        containing both header labels. Returns None while the Device tab has
        never been built (e.g. Studio still starting) or the UI isn't English.
        """
        labels: dict[str, int] = {}
        for hwnd in _children(top):
            text = _text(hwnd)
            if text in (MONITOR_LABEL, OTHERS_LABEL, PRINTER_LIST_LABEL) and _IsWindowVisible(hwnd):
                labels.setdefault(text, hwnd)
        if MONITOR_LABEL not in labels or OTHERS_LABEL not in labels:
            return None
        mon_chain = _ancestors(labels[MONITOR_LABEL])
        oth_chain = _ancestors(labels[OTHERS_LABEL])
        oth_set = set(oth_chain)
        content = next((h for h in mon_chain if h in oth_set), None)
        if not content or content == top:
            return None
        monitor_card = mon_chain[mon_chain.index(content) - 1]
        others_card = oth_chain[oth_chain.index(content) - 1]
        rows: list[int] = []
        if PRINTER_LIST_LABEL in labels:
            rows = _locate_printer_rows(labels[PRINTER_LIST_LABEL])
        return StudioLayout(top, content, monitor_card, others_card, rows)

    def _locate_printer_rows(list_label: int) -> list[int]:
        # Walk up from the "My Printer" label to the whole sidebar column.
        label_rect = window_rect(list_label)
        sidebar = list_label
        while True:
            parent = _GetParent(sidebar)
            if not parent:
                break
            sidebar = parent
            if window_rect(sidebar)[3] > 6 * label_rect[3]:
                break
        sidebar_rect = window_rect(sidebar)
        candidates = [
            (h, window_rect(h)) for h in _children(sidebar) if _IsWindowVisible(h)
        ]
        return pick_printer_rows(candidates, sidebar_rect, label_rect[1] + label_rect[3])

    def row_color(row: int) -> tuple[int, int, int] | None:
        """Background color of a printer row, read from the screen — or None
        if another window covers that spot (we only trust Studio's pixels)."""
        x, y, _w, h = window_rect(row)
        px, py = x + 4, y + h // 2
        under = _WindowFromPoint(wt.POINT(px, py))
        if not under or _GetAncestor(under, _GA_ROOT) != _GetAncestor(row, _GA_ROOT):
            return None
        hdc = _GetDC(None)
        try:
            value = _GetPixel(hdc, px, py)
        finally:
            _ReleaseDC(None, hdc)
        if value == _CLR_INVALID:
            return None
        return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)

    def ensure_clips_siblings(hwnd: int) -> None:
        """Stop a Studio card from painting over the panel we put above it.

        wx doesn't set WS_CLIPSIBLINGS, so without it every Studio repaint of
        the card would draw straight over our sibling window.
        """
        style = _GetWindowLongPtrW(hwnd, _GWL_STYLE)
        if not style & _WS_CLIPSIBLINGS:
            _SetWindowLongPtrW(hwnd, _GWL_STYLE, style | _WS_CLIPSIBLINGS)

    def is_above(ours: int, theirs: int) -> bool:
        """True if sibling ``ours`` is higher in z-order than ``theirs``."""
        h = _GetWindow(theirs, _GW_HWNDPREV)
        while h:
            if h == ours:
                return True
            h = _GetWindow(h, _GW_HWNDPREV)
        return False

    def place(hwnd: int, rect: Rect, raise_to_top: bool) -> None:
        """Move/resize a child window in exact physical pixels."""
        x, y, w, h = rect
        flags = _SWP_NOACTIVATE | (0 if raise_to_top else _SWP_NOZORDER)
        _SetWindowPos(hwnd, None, x, y, w, h, flags)  # HWND_TOP == NULL

else:  # pragma: no cover - non-Windows stubs

    def find_studio() -> int | None:
        return None

    def locate_layout(top: int) -> StudioLayout | None:
        return None

    def is_window(hwnd: int | None) -> bool:
        return False
