"""Konvertiert icon.svg -> icon.ico (16/32/48/64/128/256 px) via PySide6 + Pillow."""
import io
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

SIZES = [16, 32, 48, 64, 128, 256]
SRC = Path(__file__).parent / "icon.svg"
DST = Path(__file__).parent / "icon.ico"


def render_svg(renderer: QSvgRenderer, size: int) -> Image.Image:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    buf = img.bits().tobytes()
    pil = Image.frombytes("RGBA", (size, size), buf, "raw", "BGRA")
    return pil


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    renderer = QSvgRenderer(str(SRC))
    if not renderer.isValid():
        print(f"FEHLER: {SRC} konnte nicht geladen werden.")
        sys.exit(1)

    frames = [render_svg(renderer, s) for s in SIZES]
    frames[0].save(
        DST,
        format="ICO",
        append_images=frames[1:],
        sizes=[(s, s) for s in SIZES],
    )
    print(f"Erstellt: {DST}  ({', '.join(str(s) for s in SIZES)} px)")


if __name__ == "__main__":
    main()
