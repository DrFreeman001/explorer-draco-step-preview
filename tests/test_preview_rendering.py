"""Full-surface rendering: dropping faces or ignoring depth must fail these tests."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
import DracoPy


def renderer():
    assert importlib.util.find_spec('explorer_preview.preview_rendering'), 'Full-surface renderer is missing'
    return importlib.import_module('explorer_preview.preview_rendering')


def test_mesh_keeps_every_face_and_source_arrays(cube):
    r = renderer()
    original = cube.positions.copy()
    mesh = r.prepare_arrays(cube.positions, cube.faces)
    assert np.array_equal(mesh.faces, cube.faces)
    assert np.array_equal(cube.positions, original)
    assert mesh.positions.dtype == np.float32
    assert mesh.faces.dtype == np.uint32
    assert mesh.positions.min() == -.5 and mesh.positions.max() == .5
    assert not mesh.simplified


def test_decode_keeps_dense_surface(dense):
    r = renderer()
    data = DracoPy.encode(dense.positions, dense.faces)
    mesh = r.decode_mesh(data)
    assert len(mesh.faces) == len(dense.faces) > 12000


@pytest.mark.parametrize('points,faces', [
    ([[0,0,0],[1,0,0],[0,1,float('nan')]], [[0,1,2]]),
    ([[0,0,0],[1,0,0],[0,1,0]], [[0,1,3]]),
    ([[0,0,0],[1,0,0],[0,1,0]], [[0,-1,2]]),
    ([[0,0,0]]*3, [[0,1,2]]),
])
def test_rejects_invalid_geometry(points, faces):
    with pytest.raises(ValueError):
        renderer().prepare_arrays(np.array(points), np.array(faces))


def test_gpu_surface_is_solid_and_changes_with_camera(request, cube):
    if not native_gpu_test(request):
        return
    r = renderer()
    mesh = r.prepare_arrays(cube.positions, cube.faces)
    with r.MeshRenderer(mesh) as gpu:
        front = gpu.render(128,128,yaw=0,pitch=0)
        background = front.pixel(0,0)
        assert all(front.pixel(x,y) != background for x in range(38,90) for y in range(38,90))
        rotated = gpu.render(128,128,yaw=35,pitch=20)
        assert front != rotated
        reset = gpu.render(128,128,yaw=0,pitch=0)
        assert front == reset
        with pytest.raises(ValueError): gpu.render(0,128)
        with pytest.raises(ValueError): gpu.render(999999,128)



def test_depth_is_independent_of_triangle_submission_order(request):
    if not native_gpu_test(request):
        return
    r = renderer()
    # Near flat triangle covers an identically projected, sloping far triangle.
    points = np.array([[-1,-1,.5],[1,-1,.5],[0,1,.5],[-1,-1,-.5],[1,-1,-.2],[0,1,-.5]],dtype=np.float32)
    faces = np.array([[0,1,2],[3,4,5]],dtype=np.uint32)
    with r.MeshRenderer(r.prepare_arrays(points, faces)) as gpu:
        a = gpu.render(128,128,yaw=0,pitch=0)
    with r.MeshRenderer(r.prepare_arrays(points, faces[::-1])) as gpu:
        b = gpu.render(128,128,yaw=0,pitch=0)
    assert a == b


def test_invalid_draco_and_point_cloud():
    r = renderer()
    with pytest.raises(ValueError, match='Invalid Draco'):
        r.decode_mesh(b'bad')
    with pytest.raises(ValueError, match='point clouds'):
        r.decode_mesh(DracoPy.encode(np.array([[0.,0.,0.],[1.,1.,1.]])))


def native_gpu_test(request):
    """Qt's offscreen plugin lacks Windows GL; isolate native Qt from suite qapp."""
    if sys.platform != 'win32':
        pytest.skip('Native Windows OpenGL integration test')
    if os.environ.get('DRACOCONV_GPU_TEST_CHILD') == '1':
        request.getfixturevalue('qapp')
        return True
    env = dict(os.environ, QT_QPA_PLATFORM='windows', DRACOCONV_GPU_TEST_CHILD='1')
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', request.node.nodeid, '-q'],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return False


def tall_box(height_axis):
    """Boîte 1 × 1 × 3 dont la grande dimension suit l'axe demandé."""
    size = [1., 1., 1.]
    size[height_axis] = 3.
    corners = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])], dtype=np.float32)
    faces = np.array([[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],[2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]], dtype=np.uint32)
    return corners, faces


def silhouette(image):
    background = image.pixel(0, 0)
    cells = [(x, y) for x in range(image.width()) for y in range(image.height()) if image.pixel(x, y) != background]
    xs, ys = [c[0] for c in cells], [c[1] for c in cells]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def test_z_up_stands_a_printing_model_upright(request):
    if not native_gpu_test(request):
        return
    r = renderer()
    points, faces = tall_box(2)
    with r.MeshRenderer(r.prepare_arrays(points, faces)) as gpu:
        width, height = silhouette(gpu.render(128, 128, yaw=0, pitch=0, up='z'))
        assert height > 2 * width
        width, height = silhouette(gpu.render(128, 128, yaw=0, pitch=0, up='y'))
        assert abs(height - width) <= 2
        with pytest.raises(ValueError): gpu.render(64, 64, up='x')


def test_vertex_colours_reach_the_image(request):
    if not native_gpu_test(request):
        return
    from explorer_preview.preview_rendering import DisplayMesh, MeshRenderer
    points = np.array([[-.5, -.5, 0], [.5, -.5, 0], [.5, .5, 0], [-.5, .5, 0]], np.float32)
    faces = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
    plain = DisplayMesh(points, faces)
    red = DisplayMesh(points, faces, colors=np.tile(np.array([[255, 0, 0]], np.uint8), (4, 1)))
    images = []
    for mesh in (plain, red):
        with MeshRenderer(mesh) as renderer:
            images.append(renderer.render(64, 64, yaw=0, pitch=0).pixelColor(32, 32))
    assert images[0].blue() > images[0].red() + 60
    assert images[1].red() > 150 and images[1].green() < 20 and images[1].blue() < 20
    with pytest.raises(ValueError, match='colors'):
        MeshRenderer(DisplayMesh(points, faces, colors=np.zeros((3, 3), np.uint8)))


def test_translucent_face_lets_the_opaque_one_show_through(request):
    if not native_gpu_test(request):
        return
    from explorer_preview.preview_rendering import DisplayMesh, MeshRenderer
    square = [[-.4, -.4], [.4, -.4], [.4, .4], [-.4, .4]]
    points = np.array([[x, y, .3] for x, y in square] + [[x, y, -.3] for x, y in square], np.float32)
    colors = np.array([[255, 0, 0, 128]] * 4 + [[0, 0, 255, 255]] * 4, np.uint8)
    # Le carré rouge translucide est devant le carré bleu opaque ; les faces opaques sont listées en premier.
    faces = np.array([[4, 5, 6], [4, 6, 7], [0, 1, 2], [0, 2, 3]], np.uint32)
    with MeshRenderer(DisplayMesh(points, faces, colors=colors, opaque_faces=2)) as renderer:
        pixel = renderer.render(64, 64, yaw=0, pitch=0).pixelColor(32, 32)
    assert pixel.red() > 60 and pixel.blue() > 60 and pixel.alpha() == 255
    with MeshRenderer(DisplayMesh(points, faces, colors=colors)) as renderer:
        opaque = renderer.render(64, 64, yaw=0, pitch=0).pixelColor(32, 32)
    assert opaque.red() > 150 and opaque.blue() < 20
    with pytest.raises(ValueError, match='opaque'):
        MeshRenderer(DisplayMesh(points, faces, colors=colors, opaque_faces=5))
