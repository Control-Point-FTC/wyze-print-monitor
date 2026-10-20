"""Regenerate every icon and installer image from the master logo.

    python packaging/make_artwork.py path/to/logo.png

The source logo is a rounded-square tile on an opaque black square; the
corners are masked to real transparency (anti-aliased) so the icon looks
right on light taskbars and in the installer's light theme. Writes:

    src/wyze_print_monitor/assets/icon.png   256 px, window/tray icon
    src/wyze_print_monitor/assets/icon.ico   16-256 px, exe / shortcuts
    installer/logo-master.png                 1024 px cleaned master
    installer/wizard-side-*.png               Welcome/Finished art, 100-250% DPI
    installer/wizard-logo-*.png               page header logo, 100-250% DPI

Needs Pillow and Windows' Segoe UI fonts.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "wyze_print_monitor" / "assets"
INSTALLER = ROOT / "installer"
CORNER_RADIUS = 0.185  # of the tile size, measured from the source logo
TEXT = (138, 141, 147, 255)  # readable on both light and dark wizard themes
GREEN = (98, 211, 97, 255)
FONTS = Path("C:/Windows/Fonts")


def rounded(src: Image.Image, size: int) -> Image.Image:
    """Resize and cut the corners to transparency (4x supersampled mask)."""
    big = size * 4
    mask = Image.new("L", (big, big), 0)
    inset = round(big * 0.004)  # drop the black fringe at the very edge
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, big - 1 - inset, big - 1 - inset], radius=round(big * CORNER_RADIUS), fill=255
    )
    tile = src.convert("RGBA").resize((size, size), Image.LANCZOS)
    tile.putalpha(mask.resize((size, size), Image.LANCZOS))
    return tile


def side_image(master: Image.Image, width: int, height: int) -> Image.Image:
    k = width / 202  # designed at the 100% DPI size, 202x386
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    logo = rounded(master, round(132 * k))
    img.alpha_composite(logo, ((width - logo.width) // 2, round(92 * k)))
    draw = ImageDraw.Draw(img)
    title = ImageFont.truetype(str(FONTS / "seguisb.ttf"), round(17 * k))
    body = ImageFont.truetype(str(FONTS / "segoeui.ttf"), round(11.5 * k))
    for text, font, y in (
        ("Wyze Print Monitor", title, 242),
        ("Your printer's camera,", body, 272),
        ("inside eufyMake Studio", body, 288),
    ):
        draw.text(((width - draw.textlength(text, font=font)) / 2, round(y * k)), text, font=font, fill=TEXT)
    draw.rounded_rectangle([(width / 2 - 16 * k, 312 * k), (width / 2 + 16 * k, 315 * k)], radius=2 * k, fill=GREEN)
    return img


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    master = Image.open(sys.argv[1]).convert("RGBA")
    rounded(master, 1024).save(INSTALLER / "logo-master.png")
    rounded(master, 256).save(ASSETS / "icon.png")
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    rounded(master, 256).save(ASSETS / "icon.ico", sizes=[(s, s) for s in sizes])
    for old in list(INSTALLER.glob("wizard-*.png")) + list(INSTALLER.glob("wizard-*.bmp")):
        old.unlink()
    # Inno Setup 6.6+ image areas at 100/125/150/200/250% DPI.
    for width, height in ((202, 386), (269, 515), (336, 643), (430, 824), (534, 1022)):
        side_image(master, width, height).save(INSTALLER / f"wizard-side-{width}.png")
    for size in (58, 73, 87, 116, 145):
        rounded(master, size).save(INSTALLER / f"wizard-logo-{size}.png")
    print("artwork written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
