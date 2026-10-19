"""Tests for the eufyMake Studio window-matching logic (pure, no Win32)."""
from wyze_print_monitor.studio_win32 import (
    camera_printer_selected,
    is_selected_row_color,
    is_studio_title,
    pick_printer_rows,
    selected_row_index,
)

# Colors sampled from eufyMake Studio's "My Printer" list.
SELECTED = (53, 65, 56)
NORMAL = (41, 42, 45)


def test_studio_title_matches_both_brands():
    assert is_studio_title("*Untitled - eufyMake Studio 3D Based on PrusaSlicer")
    assert is_studio_title("benchy.3mf - AnkerMake Studio")
    assert not is_studio_title("Wyze Print Monitor")


def test_selected_row_is_the_green_tinted_one():
    assert is_selected_row_color(SELECTED)
    assert not is_selected_row_color(NORMAL)
    assert selected_row_index([SELECTED, NORMAL]) == 0
    assert selected_row_index([NORMAL, SELECTED]) == 1


def test_selection_unknown_when_covered_or_ambiguous():
    assert selected_row_index([SELECTED, None]) is None  # a row was covered
    assert selected_row_index([NORMAL, NORMAL]) is None
    assert selected_row_index([SELECTED, SELECTED]) is None
    assert selected_row_index([]) is None


def test_camera_shows_only_for_configured_printer():
    assert camera_printer_selected(0, configured_row=1, previous=False) is True
    assert camera_printer_selected(1, configured_row=1, previous=True) is False
    # "Any printer"
    assert camera_printer_selected(1, configured_row=0, previous=False) is True


def test_unknown_selection_keeps_previous_decision():
    assert camera_printer_selected(None, configured_row=1, previous=True) is True
    assert camera_printer_selected(None, configured_row=1, previous=False) is False


def test_never_shows_before_the_printer_was_read():
    """Covered sidebar / no rows on startup must not count as a match."""
    assert camera_printer_selected(None, configured_row=1, previous=None) is None
    assert camera_printer_selected(0, configured_row=1, previous=None) is True


def test_pick_printer_rows_filters_and_sorts():
    sidebar = (15, 111, 258, 895)
    header_bottom = 151
    candidates = [
        (75752, (15, 215, 256, 48)),     # row 2
        (12979198, (15, 167, 256, 48)),  # row 1
        (135028, (14, 119, 258, 39)),    # "My Printer" header bar: above header bottom
        (134810, (14, 166, 258, 1)),     # divider: too short
        (200338, (15, 167, 256, 839)),   # list panel: too tall
        (134814, (241, 126, 19, 19)),    # refresh icon: too narrow
    ]
    assert pick_printer_rows(candidates, sidebar, header_bottom) == [12979198, 75752]
