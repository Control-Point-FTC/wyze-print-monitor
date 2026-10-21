"""One design language: overlay pills and check boxes. Needs PySide6."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from wyze_print_monitor.ui import styles  # noqa: E402
from wyze_print_monitor.ui.views import CHIP_STYLES, VIEWS_QSS, set_chip  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_status_is_a_dot_not_a_colored_block(app):
    label = QtWidgets.QLabel()
    set_chip(label, "REC 00:12", styles.DOT_RED)
    assert styles.DOT_RED in label.text() and "REC 00:12" in label.text()
    assert label.styleSheet() == ""  # the look comes from the shared sheet
    set_chip(label, "")
    assert label.isHidden()


def test_every_stream_state_uses_a_palette_dot():
    dots = {styles.DOT_GREEN, styles.DOT_AMBER, styles.DOT_RED, styles.DOT_GREY}
    assert all(dot in dots for _text, dot in CHIP_STYLES.values())


def test_all_overlay_pills_share_one_look():
    for selector in ("QLabel#chip", "QPushButton#zoomChip"):
        block = VIEWS_QSS.split(selector, 1)[1].split("}", 1)[0]
        assert styles.PILL_BG in block and "border-radius: 11px" in block


def test_checkmark_image(app, tmp_path):
    rule = styles.checkmark_qss(str(tmp_path))
    assert (tmp_path / "check.png").exists() and "check.png" in rule
    assert "\\" not in rule  # Qt wants forward slashes
