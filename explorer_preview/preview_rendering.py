"""Complete indexed mesh rendering with a bounded offscreen OpenGL framebuffer.

Create/use/close MeshRenderer on the GUI thread after QApplication creation.
The decoder may run on a worker. No source faces are discarded or modified.
"""
from dataclasses import dataclass
import numpy as np
import DracoPy
from shiboken6 import VoidPtr
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat, QMatrix4x4, QVector4D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

MAX_INPUT = 64 * 1024 * 1024
MAX_VERTICES = 20_000_000
MAX_FACES = 30_000_000
DEFAULT_COLOR = (65 / 255, 135 / 255, 205 / 255)


@dataclass
class DisplayMesh:
    positions: np.ndarray
    faces: np.ndarray
    simplified: bool = False
    colors: np.ndarray | None = None  # uint8 (sommets, 3 ou 4), sRGB et opacité ; None : couleur par défaut
    opaque_faces: int | None = None  # les faces suivantes sont translucides ; None : toutes opaques


def prepare_arrays(points, faces):
    points, faces = np.asarray(points), np.asarray(faces)
    if points.ndim != 2 or points.shape[1] != 3 or not 0 < len(points) <= MAX_VERTICES:
        raise ValueError('Invalid vertex count or shape')
    if faces.ndim != 2 or faces.shape[1] != 3 or not 0 < len(faces) <= MAX_FACES:
        raise ValueError('Invalid face count or shape')
    if not np.issubdtype(faces.dtype, np.integer) or faces.min() < 0 or faces.max() >= len(points):
        raise ValueError('Invalid face indices')
    if not np.isfinite(points).all():
        raise ValueError('Non-finite geometry')
    low, high = points.min(axis=0).astype(np.float64), points.max(axis=0).astype(np.float64)
    scale = float(np.max(high - low))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('Empty geometry bounds')
    # Normalize in bounded chunks, avoiding a full float64 temporary.
    normalized = np.empty(points.shape, dtype=np.float32)
    center = (low + high) / 2
    for start in range(0, len(points), 262144):
        normalized[start:start+262144] = (points[start:start+262144] - center) / scale
    return DisplayMesh(normalized, np.ascontiguousarray(faces, dtype=np.uint32))


def decode_mesh(data):
    if not data or len(data) > MAX_INPUT:
        raise ValueError('Input exceeds preview limit or is empty')
    try:
        mesh = DracoPy.decode(data)
    except Exception as exc:
        raise ValueError('Invalid Draco input') from exc
    faces = getattr(mesh, 'faces', None)
    if faces is None or not len(faces):
        raise ValueError('Draco point clouds are not supported by this preview')
    return prepare_arrays(mesh.points, faces)


_VERTEX = '''#version 120
attribute vec3 position;
attribute vec4 color;
varying vec4 surfaceColor;
uniform mat4 rotation;
uniform mat4 projection;
varying vec3 surfacePosition;
void main() {
    vec4 p = rotation * vec4(position, 1.0);
    surfacePosition = p.xyz;
    surfaceColor = color;
    gl_Position = projection * p;
}
'''
_FRAGMENT = '''#version 120
varying vec3 surfacePosition;
varying vec4 surfaceColor;
void main() {
    vec3 n = normalize(cross(dFdx(surfacePosition), dFdy(surfacePosition)));
    float light = 0.35 + 0.65 * abs(dot(n, normalize(vec3(-0.35,0.5,1.0))));
    gl_FragColor = vec4(surfaceColor.rgb*light, surfaceColor.a);
}
'''


class MeshRenderer:
    """Reusable full-mesh GPU renderer; raises RuntimeError if OpenGL unavailable.

    The caller should show the error instead of publishing a blank thumbnail.
    No decimation occurs. CPU arrays need not be retained after construction.
    """
    def __init__(self, mesh):
        self.buffers = []
        self.fbo = None
        self.program = None
        self.closed = False
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setDepthBufferSize(24)
        self.context = QOpenGLContext()
        self.context.setFormat(fmt)
        if not self.context.create():
            raise RuntimeError('OpenGL context unavailable')
        self.surface = QOffscreenSurface()
        self.surface.setFormat(self.context.format())
        self.surface.create()
        if not self.surface.isValid() or not self.context.makeCurrent(self.surface):
            raise RuntimeError('OpenGL offscreen surface unavailable')
        try:
            self.gl = self.context.functions()
            self.gl.initializeOpenGLFunctions()
            self.driver = self.gl.glGetString(0x1F01)
            self.program = QOpenGLShaderProgram()
            for stage, code in [(QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX), (QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT)]:
                if not self.program.addShaderFromSourceCode(stage, code):
                    raise RuntimeError('OpenGL shader unavailable: ' + self.program.log())
            self.program.bindAttributeLocation('position', 0)
            self.program.bindAttributeLocation('color', 1)
            if not self.program.link():
                raise RuntimeError('OpenGL program unavailable: ' + self.program.log())
            colors = getattr(mesh, 'colors', None)
            if colors is not None and (colors.dtype != np.uint8 or colors.ndim != 2 or len(colors) != len(mesh.positions)
                                       or colors.shape[1] not in (3, 4)):
                raise ValueError('Invalid vertex colors')
            self.colored = colors is not None
            arrays = [(QOpenGLBuffer.Type.VertexBuffer, mesh.positions), (QOpenGLBuffer.Type.IndexBuffer, mesh.faces)]
            if self.colored:
                arrays.append((QOpenGLBuffer.Type.VertexBuffer, np.ascontiguousarray(colors)))
            for kind, array in arrays:
                buffer = QOpenGLBuffer(kind)
                self.buffers.append(buffer)
                if not buffer.create() or not buffer.bind():
                    raise RuntimeError('OpenGL buffer unavailable')
                buffer.allocate(array.nbytes)
                buffer.write(0, VoidPtr(array.ctypes.data, array.nbytes), array.nbytes)
                if self.gl.glGetError():
                    raise RuntimeError('OpenGL mesh allocation failed')
            self.count = int(mesh.faces.size)
            opaque = getattr(mesh, 'opaque_faces', None)
            if opaque is not None and not 0 <= opaque <= len(mesh.faces):
                raise ValueError('Invalid opaque face count')
            self.opaque = self.count if opaque is None else int(opaque) * 3
            self.components = colors.shape[1] if self.colored else 4
        except Exception:
            self.close()
            raise
        finally:
            self.context.doneCurrent()

    def render(self, width, height, yaw=30., pitch=-20., zoom=1., up='y'):
        """up='z' tient debout un modèle d'impression 3D (Z vertical, comme dans les trancheurs)."""
        if up not in ('y', 'z'):
            raise ValueError('Vertical axis must be y or z')
        if not (1 <= width <= 2048 and 1 <= height <= 2048):
            raise ValueError('Framebuffer dimensions must be between 1 and 2048')
        if not np.isfinite([yaw, pitch, zoom]).all():
            raise ValueError('Non-finite camera')
        if self.closed or not self.context.makeCurrent(self.surface):
            raise RuntimeError('OpenGL context unavailable')
        try:
            if self.fbo is None or self.fbo.width() != width or self.fbo.height() != height:
                self.fbo = None
                fmt = QOpenGLFramebufferObjectFormat()
                fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
                self.fbo = QOpenGLFramebufferObject(width, height, fmt)
            if not self.fbo.isValid() or not self.fbo.bind():
                raise RuntimeError('OpenGL framebuffer unavailable')
            gl = self.gl
            gl.glViewport(0, 0, width, height)
            gl.glClearColor(238/255, 241/255, 245/255, 1.)
            gl.glClear(0x4000 | 0x0100)
            gl.glEnable(0x0B71)  # depth test
            self.program.bind()
            self.buffers[0].bind()
            self.program.enableAttributeArray(0)
            self.program.setAttributeBuffer(0, 0x1406, 0, 3, 12)
            if self.colored:
                self.buffers[2].bind()
                self.program.enableAttributeArray(1)
                self.program.setAttributeBuffer(1, 0x1401, 0, self.components, self.components)  # octets non signés, normalisés par Qt
            else:
                self.program.disableAttributeArray(1)
                self.program.setAttributeValue(1, QVector4D(*DEFAULT_COLOR, 1.))
            self.buffers[1].bind()
            rotation = QMatrix4x4()
            rotation.rotate(float(pitch), 1, 0, 0)
            rotation.rotate(float(yaw), 0, 1, 0)
            if up == 'z':
                rotation.rotate(-90., 1, 0, 0)
            projection = QMatrix4x4()
            zoom = float(np.clip(zoom, .2, 5.))
            extent = .5 / (.72 * zoom)
            projection.ortho(-extent*width/min(width,height), extent*width/min(width,height), -extent*height/min(width,height), extent*height/min(width,height), -10, 10)
            self.program.setUniformValue('rotation', rotation)
            self.program.setUniformValue('projection', projection)
            gl.glDisable(0x0BE2)  # mélange
            gl.glDepthMask(True)
            if self.opaque:
                gl.glDrawElements(0x0004, self.opaque, 0x1405, VoidPtr(0))
            if self.opaque < self.count:
                # Faces translucides : après les opaques, sans écrire la profondeur ; l'alpha de l'image reste à 1.
                gl.glEnable(0x0BE2)
                gl.glBlendFuncSeparate(0x0302, 0x0303, 0, 1)
                gl.glDepthMask(False)
                gl.glDrawElements(0x0004, self.count - self.opaque, 0x1405, VoidPtr(self.opaque * 4))
                gl.glDepthMask(True)
                gl.glDisable(0x0BE2)
            if gl.glGetError():
                raise RuntimeError('OpenGL draw failed')
            image = self.fbo.toImage()
            if image.isNull():
                raise RuntimeError('OpenGL readback failed')
            return image
        finally:
            self.context.doneCurrent()

    def close(self):
        if not self.closed:
            if self.context.makeCurrent(self.surface):
                self.fbo = None
                for buffer in self.buffers:
                    buffer.destroy()
                self.program = None
                self.context.doneCurrent()
            self.surface.destroy()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


