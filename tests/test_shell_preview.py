import numpy as np
import pytest
import DracoPy
from explorer_preview.shell_preview import prepare_mesh, project, render_image


def encoded():
    return DracoPy.encode(np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]), np.array([[0,1,2],[0,2,3]], dtype=np.uint32))


def stored(tmp_path, data=None):
    path = tmp_path / 'input.drc'
    path.write_bytes(encoded() if data is None else data)
    return path


def test_invalid_and_point_cloud():
    with pytest.raises(ValueError): prepare_mesh(b'invalid')
    with pytest.raises(ValueError, match='point'): prepare_mesh(DracoPy.encode(np.array([[0.,0.,0.],[1.,1.,1.]])))


def test_projection_does_not_mutate_and_face_cap():
    tris, reduced = prepare_mesh(encoded(), 1)
    assert tris.shape == (1,3,3) and reduced
    original = tris.copy()
    moved = project(tris, 30, 20, 1.5)
    assert np.array_equal(original, tris)
    assert not np.array_equal(moved, tris)


def test_thumbnail_has_geometry(qapp, tmp_path):
    tris, _ = prepare_mesh(encoded())
    image = render_image(tris, 128)
    assert image.width() == image.height() == 128
    assert image.save(str(tmp_path / 'thumb.png'))
    assert len({image.pixel(x,y) for x in range(128) for y in range(128)}) > 2


def test_thumbnail_uses_every_face_when_opengl_works(monkeypatch, tmp_path):
    from explorer_preview import shell_preview
    calls = {}

    class FakeRenderer:
        def __init__(self, mesh):
            calls['faces'] = len(mesh.faces)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            calls['closed'] = True
        def render(self, width, height, up='y', **_):
            calls['render'] = (width, height, up)
            return 'image'

    monkeypatch.setattr(shell_preview.gpu_rendering, 'MeshRenderer', FakeRenderer)
    image, simplified = shell_preview.render_thumbnail(stored(tmp_path), 5000)
    assert image == 'image' and not simplified
    assert calls == {'faces': 2, 'render': (1024, 1024, 'z'), 'closed': True}


def test_thumbnail_falls_back_to_sampled_drawing_without_opengl(qapp, monkeypatch, tmp_path):
    from explorer_preview import shell_preview

    def unavailable(mesh):
        raise RuntimeError('OpenGL context unavailable')

    monkeypatch.setattr(shell_preview.gpu_rendering, 'MeshRenderer', unavailable)
    image, simplified = shell_preview.render_thumbnail(stored(tmp_path), 64)
    assert image.width() == 64 and not simplified


def test_invalid_input_is_not_hidden_by_the_fallback(tmp_path):
    from explorer_preview import shell_preview
    with pytest.raises(ValueError):
        shell_preview.render_thumbnail(stored(tmp_path, b'invalid'), 64)


def test_preview_limit_matches_renderer_limit():
    from explorer_preview import preview_rendering, shell_preview
    assert shell_preview.MAX_INPUT == preview_rendering.MAX_INPUT == 64 * 1024 * 1024


def test_load_model_reads_draco_by_content(tmp_path):
    from explorer_preview import shell_preview
    mesh = shell_preview.load_model(stored(tmp_path))
    assert len(mesh.faces) == 2


def test_load_model_rejects_oversized_and_empty_inputs(tmp_path, monkeypatch):
    from explorer_preview import shell_preview
    with pytest.raises(ValueError, match='limit'):
        shell_preview.load_model(stored(tmp_path, b''))
    monkeypatch.setattr(shell_preview, 'MAX_INPUT', 10)
    with pytest.raises(ValueError, match='limit'):
        shell_preview.load_model(stored(tmp_path))


def test_load_model_sends_step_to_the_step_reader(tmp_path, monkeypatch):
    from explorer_preview import shell_preview
    calls = []
    monkeypatch.setattr(shell_preview.step_preview, 'mesh_step', lambda source, output: calls.append((source, output)) or 'mesh')
    source = stored(tmp_path, b'ISO-10303-21;\nHEADER;\n')
    assert shell_preview.load_model(source) == 'mesh'
    assert calls == [(source, tmp_path / 'model.mesh')]


def test_sampled_fallback_comes_from_the_decoded_mesh(tmp_path):
    from explorer_preview import shell_preview
    mesh = shell_preview.load_model(stored(tmp_path))
    tris, reduced = shell_preview.sample_triangles(mesh, 1)
    assert tris.shape == (1, 3, 3) and reduced


def test_step_has_its_own_larger_size_limit(tmp_path, monkeypatch):
    from explorer_preview import shell_preview
    assert shell_preview.step_preview.MAX_INPUT == 200 * 1024 * 1024
    source = stored(tmp_path, b'ISO-10303-21;' + b' ' * 100)
    monkeypatch.setattr(shell_preview, 'MAX_INPUT', 10)
    monkeypatch.setattr(shell_preview.step_preview, 'mesh_step', lambda source, output: 'mesh')
    assert shell_preview.load_model(source) == 'mesh'
    monkeypatch.setattr(shell_preview.step_preview, 'MAX_INPUT', 50)
    with pytest.raises(ValueError, match='limit'):
        shell_preview.load_model(source)


@pytest.mark.parametrize('key, facing', [
    (1, (0, 0, 1)),    # dessus : on voit la face +Z
    (2, (0, 0, -1)),   # dessous
    (3, (0, -1, 0)),   # face : depuis -Y, comme les trancheurs
    (4, (0, 1, 0)),    # arrière
    (5, (-1, 0, 0)),   # gauche : depuis -X
    (6, (1, 0, 0)),    # droite
])
def test_preset_views_face_the_expected_side(key, facing):
    """Avec Z vertical, la vue n montre au spectateur le côté attendu du modèle."""
    from explorer_preview.shell_preview import PRESET_VIEWS

    yaw, pitch = PRESET_VIEWS[key]
    point = np.array(facing, dtype=float)
    # Même passage Z vertical → Y écran que le rendu (sample_triangles), puis la caméra.
    upright = np.array([[point[0], point[2], -point[1]]])
    toward_viewer = project(upright[None], yaw, pitch, 1.)[0, 0, 2]
    assert toward_viewer == pytest.approx(1.)


def test_number_keys_switch_views(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from explorer_preview import shell_preview

    widget = shell_preview.Preview.__new__(shell_preview.Preview)
    monkeypatch.setattr(shell_preview.Preview, 'update', lambda self: None)
    widget.yaw, widget.pitch, widget.zoom = 12., 34., 2.5

    def press(key):
        shell_preview.Preview.keyPressEvent(widget, QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    press(Qt.Key.Key_1)
    assert (widget.yaw, widget.pitch, widget.zoom) == (0., 90., 2.5)  # le zoom choisi reste
    press(Qt.Key.Key_0)
    assert (widget.yaw, widget.pitch, widget.zoom) == shell_preview.DEFAULT_VIEW


def _cube_mesh(size_mm=20.0):
    from explorer_preview.preview_rendering import prepare_arrays

    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], np.uint32)
    return prepare_arrays(v * size_mm, f)


def test_view_matrix_matches_the_fallback_projection():
    from explorer_preview.shell_preview import view_matrix

    point = np.array([0.3, -0.2, 0.4])
    upright = np.array([[[point[0], point[2], -point[1]]]])
    for yaw, pitch in ((30, 20), (0, 90), (-90, 0), (180, -45)):
        assert np.allclose(view_matrix(yaw, pitch) @ point, project(upright, yaw, pitch, 1.)[0, 0])


def test_pick_hits_the_visible_face_and_measures_in_mm():
    from explorer_preview.shell_preview import PRESET_VIEWS, mm_per_unit, pick, to_screen

    mesh = _cube_mesh(20.0)
    assert mm_per_unit(mesh) == pytest.approx(20.0)
    top = pick(mesh, 200, 150, 400, 300, *PRESET_VIEWS[1], 1.)
    assert top[2] == pytest.approx(0.5)  # vue de dessus : la face du haut
    front = pick(mesh, 200, 150, 400, 300, *PRESET_VIEWS[3], 1.)
    assert front[1] == pytest.approx(-0.5)  # vue de face : la face avant (-Y)
    assert pick(mesh, 5, 5, 400, 300, *PRESET_VIEWS[1], 1.) is None  # à côté du modèle
    # Deux coins opposés de la face du haut, vus de dessus : diagonale de 20 × √2 mm.
    corners = np.array([[-0.5, -0.5, 0.5], [0.5, 0.5, 0.5]]) * 0.98
    sx, sy, _ = to_screen(corners, 400, 300, *PRESET_VIEWS[1], 1.)
    a = pick(mesh, sx[0], sy[0], 400, 300, *PRESET_VIEWS[1], 1.)
    b = pick(mesh, sx[1], sy[1], 400, 300, *PRESET_VIEWS[1], 1.)
    assert np.linalg.norm(b - a) * mm_per_unit(mesh) == pytest.approx(20 * 0.98 * np.sqrt(2), rel=1e-3)


def test_measure_mode_clicks_and_drags(qapp, monkeypatch):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent
    from explorer_preview import shell_preview

    widget = shell_preview.Preview.__new__(shell_preview.Preview)
    monkeypatch.setattr(shell_preview.Preview, 'update', lambda self: None)
    monkeypatch.setattr(shell_preview.Preview, 'width', lambda self: 400)
    monkeypatch.setattr(shell_preview.Preview, 'height', lambda self: 300)
    monkeypatch.setattr(shell_preview.Preview, 'setFocus', lambda self: None)
    widget.mesh, widget.points, widget.measuring, widget.press, widget.drag = _cube_mesh(), [], False, None, None
    widget.yaw, widget.pitch, widget.zoom = 0., 90., 1.

    def key(k):
        shell_preview.Preview.keyPressEvent(widget, QKeyEvent(QKeyEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))

    def click(x, y, to=None):
        down = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        end = to or (x, y)
        up = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(*end), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        shell_preview.Preview.mousePressEvent(widget, down)
        shell_preview.Preview.mouseReleaseEvent(widget, up)

    click(200, 150)
    assert widget.points == []  # hors du mode mesure, un clic ne pose rien
    key(Qt.Key.Key_M)
    click(150, 120)
    click(150, 120, to=(250, 200))  # glisser : rotation, pas de point
    assert len(widget.points) == 1
    click(250, 180)
    assert len(widget.points) == 2 and 'mm' in widget.distance_text()
    click(200, 150)
    assert len(widget.points) == 1  # un troisième clic recommence
    key(Qt.Key.Key_Escape)
    assert not widget.measuring and widget.points == []
