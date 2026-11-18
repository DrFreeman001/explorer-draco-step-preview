"""Enregistre les images d'une animation du volet d'aperçu (le vrai widget Preview, dans une fenêtre hôte).

Usage : python tools/record_preview.py <modèle> <dossier d'images> [--lang fr|en] [--size 760x560]
La rotation et les vues sont pilotées par le code (lacet, tangage), comme le feraient la souris et les touches
0 à 6. Une légende indique la touche de chaque vue. Assembler ensuite avec tools/make_webp.py.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("fr", "en"), default="fr")
    parser.add_argument("--size", default="760x560")
    args = parser.parse_args()
    width, height = (int(v) for v in args.size.split("x"))

    from PySide6.QtCore import QEventLoop, QRect, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPainter
    from PySide6.QtWidgets import QApplication, QWidget

    from explorer_preview import shell_preview

    french = args.lang == "fr"
    shell_preview.TEXT = shell_preview.TEXTS[french]
    original_describe = shell_preview.describe
    shell_preview.describe = lambda mesh, french=french: original_describe(mesh, french)

    work = Path(tempfile.mkdtemp(prefix="preview-record-"))
    source = work / ("model" + args.model.suffix)
    shutil.copy2(args.model, source)  # le widget écrit un fichier « ready » à côté du modèle
    app = QApplication(sys.argv)
    host = QWidget()
    host.setWindowTitle("preview")
    host.resize(width, height)
    host.show()
    preview = shell_preview.Preview(str(source), int(host.winId()))

    def settle(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    while not preview.has_model() and not preview.message.strip(". …").startswith(("Input", "Mesh")):
        settle(100)
    settle(400)
    args.out.mkdir(parents=True, exist_ok=True)
    count = 0
    names = {1: ("dessus", "top"), 3: ("face", "front"), 6: ("droite", "right"), 0: ("vue de départ", "starting view")}

    def frame(yaw: float, pitch: float, caption: str = "") -> None:
        nonlocal count
        preview.yaw, preview.pitch = yaw, pitch
        preview.repaint()
        app.processEvents()
        image = preview.grab().toImage()
        if caption:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            font = QFont("Segoe UI", 13, QFont.Weight.DemiBold)
            painter.setFont(font)
            box = QRect(14, 14, 16 + painter.fontMetrics().horizontalAdvance(caption), 36)
            painter.setBrush(QColor(38, 56, 76, 220))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box, 8, 8)
            painter.setPen(QColor("white"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, caption)
            painter.end()
        image.save(str(args.out / f"{count:04d}.png"))
        count += 1

    start_yaw, start_pitch = shell_preview.DEFAULT_VIEW[:2]
    drag = "glisser : rotation" if french else "drag: rotate"
    for i in range(80):  # un tour complet, avec un léger mouvement de tangage
        frame(start_yaw + 360 * i / 80, start_pitch + 12 * __import__("math").sin(i / 80 * 6.283), drag)
    yaw, pitch = start_yaw, start_pitch
    for key in (1, 3, 6, 0):
        target = shell_preview.PRESET_VIEWS[key]
        caption = (f"touche {key} : " if french else f"key {key}: ") + names[key][0 if french else 1]
        for step in range(1, 9):  # transition douce vers la vue
            t = step / 8
            frame(yaw + (target[0] - yaw) * t, pitch + (target[1] - pitch) * t, caption)
        for _ in range(16):
            frame(*target, caption)
        yaw, pitch = target
    print(count, "images")
    app.quit()
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
