"""Isolated Shell preview helper for Draco and STEP: full OpenGL rendering, sampled drawing as a fallback."""
from __future__ import annotations
import argparse
import ctypes
import math
from pathlib import Path
import sys
import threading
import numpy as np
from PySide6.QtCore import Qt, QPointF, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget
from explorer_preview import preview_rendering as gpu_rendering
from explorer_preview import mesh_formats, preview_temp, step_preview

MAX_INPUT = gpu_rendering.MAX_INPUT
# Les modèles d'impression 3D ont Z vertical, comme dans les trancheurs.
UP_AXIS = 'z'
def _french() -> bool:
    """Textes en français si l'interface de Windows l'est ; en anglais sinon."""
    try:
        return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0C
    except (AttributeError, OSError):
        return False


FRENCH = _french()
TEXTS = {
    True: {'loading': 'Chargement…', 'simplified': 'Affichage simplifié · ',
           'hint': 'Glisser : rotation · Molette : zoom · 1 dessus, 3 face, 5 gauche, 6 droite · 0 ou R : vue de départ',
           'triangles': 'triangles'},
    False: {'loading': 'Loading…', 'simplified': 'Simplified drawing · ',
            'hint': 'Drag: rotate · Wheel: zoom · 1 top, 3 front, 5 left, 6 right · 0 or R: starting view',
            'triangles': 'triangles'},
}
TEXT = TEXTS[FRENCH]
SIMPLIFIED = TEXT['simplified']


def describe(mesh, french: bool = FRENCH) -> str:
    """« 120,0 × 80,0 × 45,2 mm · 459 312 triangles » : encombrement X × Y × Z (Z vertical) et nombre de faces."""
    def number(value: float, decimals: int) -> str:
        text = f'{value:,.{decimals}f}'
        return text.replace(',', '\u202f').replace('.', ',') if french else text

    parts = []
    if mesh.size is not None:
        size = [v * mesh.unit_mm for v in mesh.size]
        decimals = 2 if max(size) < 10 else 1
        parts.append(' × '.join(number(v, decimals) for v in size) + ' mm')
    parts.append(number(len(mesh.faces), 0) + ' ' + TEXTS[french]['triangles'])
    return ' · '.join(parts)
# Vue de trois quarts, légèrement par-dessus (lacet, tangage, zoom).
DEFAULT_VIEW = (30., 20., 1.)
# Vues des touches 0 à 6, comme dans Bambu Studio, OrcaSlicer et PrusaSlicer (lacet, tangage), Z vertical :
# 0 trois quarts, 1 dessus, 2 dessous, 3 face (depuis -Y), 4 arrière, 5 gauche (depuis -X), 6 droite.
PRESET_VIEWS = {0: DEFAULT_VIEW[:2], 1: (0., 90.), 2: (0., -90.), 3: (0., 0.), 4: (180., 0.), 5: (90., 0.),
                6: (-90., 0.)}


def load_model(path: Path):
    """Maillage complet du fichier (Draco, STEP, STL, OBJ ou 3MF), reconnu par son contenu et non par son nom."""
    path = Path(path)
    size = path.stat().st_size
    with path.open('rb') as source:
        head = source.read(4096)
    if step_preview.is_step(head):
        if size > step_preview.MAX_INPUT:
            raise ValueError('Input exceeds preview limit')
        return step_preview.mesh_step(path, path.with_name('model.mesh'))
    if head.startswith(b'DRACO'):
        if not 0 < size <= MAX_INPUT:
            raise ValueError('Input exceeds preview limit or is empty')
        return gpu_rendering.decode_mesh(path.read_bytes())
    kind = mesh_formats.detect(head, size)
    if kind is None:
        if not 0 < size <= MAX_INPUT:
            raise ValueError('Input exceeds preview limit or is empty')
        return gpu_rendering.decode_mesh(path.read_bytes())
    if size > mesh_formats.MAX_INPUT:
        raise ValueError('Input exceeds preview limit')
    return mesh_formats.LOADERS[kind](path.read_bytes())


def prepare_mesh(data: bytes, face_limit: int = 12000, up: str = UP_AXIS):
    """Échantillon de faces d'un contenu Draco, pour le dessin de secours."""
    return sample_triangles(gpu_rendering.decode_mesh(data), face_limit, up)


def sample_triangles(mesh, face_limit: int = 12000, up: str = UP_AXIS):
    """Échantillon de faces pour le dessin de secours, quand OpenGL manque."""
    faces = mesh.faces
    reduced = len(faces) > face_limit
    faces = faces[::max(1, math.ceil(len(faces) / face_limit))]
    triangles = mesh.positions[faces].astype(np.float64)
    if up == 'z':
        # Rotation de -90° autour de X : Z devient la verticale de l'écran.
        triangles = np.stack([triangles[..., 0], triangles[..., 2], -triangles[..., 1]], axis=-1)
    return triangles, reduced


def project(triangles, yaw=30., pitch=-20., zoom=1.):
    y, p = np.radians([yaw, pitch])
    ry = np.array([[np.cos(y),0,np.sin(y)],[0,1,0],[-np.sin(y),0,np.cos(y)]])
    rx = np.array([[1,0,0],[0,np.cos(p),-np.sin(p)],[0,np.sin(p),np.cos(p)]])
    return triangles @ (rx @ ry).T * np.clip(zoom, .2, 5.)


def paint_mesh(painter, triangles, width, height, yaw=30., pitch=-20., zoom=1.):
    painter.fillRect(0, 0, width, height, QColor('#eef1f5'))
    transformed = project(triangles, yaw, pitch, zoom)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for tri in transformed[np.argsort(transformed[:,:,2].mean(axis=1))]:
        normal = np.cross(tri[1]-tri[0], tri[2]-tri[0])
        norm = np.linalg.norm(normal)
        light = .45 + .5 * abs(float(normal[2] / norm)) if norm else .45
        painter.setBrush(QColor(int(65*light), int(135*light), int(205*light)))
        painter.drawPolygon(QPolygonF([QPointF(width/2+x*min(width,height)*.72, height/2-y*min(width,height)*.72) for x,y,z in tri]))


def render_image(triangles, size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    paint_mesh(painter, triangles, size, size, *DEFAULT_VIEW)
    painter.end()
    return image


def render_thumbnail(source: Path, size: int):
    """Miniature de toutes les faces ; dessin échantillonné seulement si OpenGL manque.

    Renvoie (image, simplifiée). Un fichier invalide lève ValueError, sans repli.
    """
    size = max(16, min(size, 1024))
    mesh = load_model(source)
    try:
        with gpu_rendering.MeshRenderer(mesh) as renderer:
            yaw, pitch, zoom = DEFAULT_VIEW
            return renderer.render(size, size, yaw=yaw, pitch=pitch, zoom=zoom, up=UP_AXIS), False
    except RuntimeError:
        triangles, reduced = sample_triangles(mesh)
        return render_image(triangles, size), reduced


class Preview(QWidget):
    loaded = Signal(object, str)

    def __init__(self, source, parent_hwnd):
        super().__init__()
        self.triangles = None
        self.renderer = None
        self.message = TEXT['loading']
        self.info = ''
        self.yaw, self.pitch, self.zoom = DEFAULT_VIEW
        self.drag = None
        self.parent_hwnd = parent_hwnd
        self.source = source
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.loaded.connect(self.ready)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.resize(480, 400)
        hwnd = int(self.winId())
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.SetParent.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        previous = user32.SetParent(hwnd, parent_hwnd)
        if not previous and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW(hwnd, -16, 0x40000000 | 0x10000000 | 0x04000000)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync_parent)
        self.timer.start(100)
        self.show()
        threading.Thread(target=self.load, args=(source,), daemon=True).start()

    def load(self, source):
        try:
            self.loaded.emit(load_model(Path(source)), '')
        except Exception as exc:
            self.loaded.emit(None, str(exc))

    def ready(self, mesh, message):
        # Le contexte OpenGL se crée ici, sur le fil de l'interface.
        if mesh is not None:
            self.info = describe(mesh)
            try:
                self.renderer = gpu_rendering.MeshRenderer(mesh)
                QApplication.instance().aboutToQuit.connect(self.renderer.close)
            except RuntimeError:
                self.triangles, reduced = sample_triangles(mesh)
                message = SIMPLIFIED if reduced else ''
        self.message = message
        Path(self.source).with_name("ready").touch()
        self.update()

    def has_model(self):
        return self.renderer is not None or self.triangles is not None

    def sync_parent(self):
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
        if not user32.IsWindow(self.parent_hwnd):
            QApplication.quit()
            return
        rect = wintypes.RECT()
        if not user32.GetClientRect(self.parent_hwnd, ctypes.byref(rect)):
            QApplication.quit()
            return
        ratio = self.devicePixelRatioF()
        self.setGeometry(0,0,round(rect.right / ratio),round(rect.bottom / ratio))

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.renderer is not None:
            ratio = self.devicePixelRatioF()
            width = max(1, min(2048, round(self.width() * ratio)))
            height = max(1, min(2048, round(self.height() * ratio)))
            try:
                image = self.renderer.render(width, height, self.yaw, self.pitch, self.zoom, up=UP_AXIS)
                image.setDevicePixelRatio(ratio)
                painter.drawImage(self.rect(), image)
            except RuntimeError as exc:
                painter.fillRect(self.rect(), QColor('#eef1f5'))
                self.message = str(exc)
        elif self.triangles is not None:
            paint_mesh(painter,self.triangles,self.width(),self.height(),self.yaw,self.pitch,self.zoom)
        else:
            painter.fillRect(self.rect(), QColor('#eef1f5'))
        painter.setPen(QColor('#26384c'))
        painter.drawText(self.rect().adjusted(10,10,-10,-10), Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, (self.info + '\n' if self.info else '') + self.message + (TEXT['hint'] if self.has_model() else ''))

    def mousePressEvent(self, event):
        self.drag = event.position()
        self.setFocus()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.position() - self.drag
            self.yaw += delta.x() * .5
            self.pitch += delta.y() * .5
            self.drag = event.position()
            self.update()

    def wheelEvent(self, event):
        self.zoom = float(np.clip(self.zoom * 1.15 ** (event.angleDelta().y()/120), .2, 5))
        self.update()

    def focusNextPrevChild(self, forward):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW(self.parent_hwnd, 0x8001, 0x09, 0)
        return True

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_R:
            self.yaw, self.pitch, self.zoom = DEFAULT_VIEW
            self.update()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_6:
            # Vue prédéfinie : le zoom reste celui choisi, sauf pour la vue de départ.
            self.yaw, self.pitch = PRESET_VIEWS[key - Qt.Key.Key_0]
            if key == Qt.Key.Key_0:
                self.zoom = DEFAULT_VIEW[2]
            self.update()
        else:
            super().keyPressEvent(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output')
    parser.add_argument('--size', type=int, default=256)
    parser.add_argument('--parent', type=int)
    args = parser.parse_args()
    # Ramasse les dossiers temporaires laissés par un hôte d'aperçu qui a planté ; ne doit jamais gêner l'aperçu.
    jobs = Path(args.input).resolve().parent.parent
    if jobs.name == 'DracoConvPreview':
        try:
            preview_temp.collect_stale(jobs)
        except Exception:
            pass
    app = QApplication([])
    if args.output:
        image, _ = render_thumbnail(Path(args.input), args.size)
        return 0 if image.save(args.output) else 2
    widget = Preview(args.input, args.parent)
    return app.exec()

if __name__ == '__main__':
    sys.exit(main())
