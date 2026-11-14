import os
import sys
from pathlib import Path
import shutil
import numpy as np
import pytest
from explorer_preview import step_preview

BLOCK = Path(__file__).parent / 'data' / 'tall_block.step'
needs_tool = pytest.mark.skipif(not step_preview.STEP_TOOL.exists(), reason='step_mesh.exe not built')


def write_mesh(path, points, faces, magic=step_preview.MAGIC, counts=None, colors=None):
    points = np.asarray(points, np.float32)
    faces = np.asarray(faces, np.uint32)
    counts = counts or (len(points), len(faces))
    colors = np.full((len(points), 4), 255, np.uint8) if colors is None else np.asarray(colors, np.uint8)
    path.write_bytes(magic + np.asarray(counts, '<u4').tobytes() + points.tobytes() + faces.tobytes() + colors.tobytes())


def test_recognizes_step_header():
    assert step_preview.is_step(b'ISO-10303-21;\nHEADER;')
    assert step_preview.is_step(b'\xef\xbb\xbf \r\n\tISO-10303-21;')
    assert not step_preview.is_step(b'DRACO\x02\x02')
    assert not step_preview.is_step(b'')


def test_reads_compact_mesh(tmp_path):
    path = tmp_path / 'model.mesh'
    write_mesh(path, [[0, 0, 0], [2, 0, 0], [0, 4, 0]], [[0, 1, 2]])
    mesh = step_preview.read_mesh_file(path)
    assert mesh.faces.tolist() == [[0, 1, 2]]
    assert np.isclose(np.ptp(mesh.positions, axis=0).max(), 1.0)


@pytest.mark.parametrize('case', ['magic', 'truncated', 'index', 'counts'])
def test_rejects_corrupt_mesh_files(tmp_path, case):
    path = tmp_path / 'model.mesh'
    points, faces = [[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]
    if case == 'magic':
        write_mesh(path, points, faces, magic=b'NOTMESH\0')
    elif case == 'truncated':
        write_mesh(path, points, faces)
        path.write_bytes(path.read_bytes()[:-4])
    elif case == 'index':
        write_mesh(path, points, [[0, 1, 3]])
    else:
        write_mesh(path, points, faces, counts=(3, 2))
    with pytest.raises(ValueError):
        step_preview.read_mesh_file(path)


def test_missing_reader_is_reported(tmp_path):
    with pytest.raises(ValueError, match='STEP reader'):
        step_preview.mesh_step(BLOCK, tmp_path / 'model.mesh', tool=tmp_path / 'absent.exe')


@needs_tool
def test_meshes_a_real_step_file_without_touching_it(tmp_path):
    source = tmp_path / 'input.drc'
    shutil.copyfile(BLOCK, source)
    before = source.read_bytes()
    mesh = step_preview.mesh_step(source, tmp_path / 'model.mesh')
    assert len(mesh.faces) > 12
    extent = np.ptp(mesh.positions, axis=0)
    # Bloc de 20 x 10 x 40 mm : la hauteur Z est la plus grande dimension.
    assert np.allclose(extent, [0.5, 0.25, 1.0], atol=0.01)
    assert source.read_bytes() == before
    assert not (tmp_path / 'model.mesh').exists()


@needs_tool
def test_invalid_step_is_rejected(tmp_path):
    source = tmp_path / 'input.drc'
    source.write_bytes(b'ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n')
    with pytest.raises(ValueError, match='STEP'):
        step_preview.mesh_step(source, tmp_path / 'model.mesh')
    assert not (tmp_path / 'model.mesh').exists()


def test_reads_vertex_colors(tmp_path):
    path = tmp_path / 'model.mesh'
    write_mesh(path, [[0, 0, 0], [2, 0, 0], [0, 4, 0]], [[0, 1, 2]], colors=[[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]])
    mesh = step_preview.read_mesh_file(path)
    assert mesh.colors.dtype == np.uint8 and mesh.colors.tolist() == [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]]
    assert mesh.opaque_faces is None


@needs_tool
def test_uncoloured_step_gets_the_default_colour(tmp_path):
    mesh = step_preview.mesh_step(BLOCK, tmp_path / 'model.mesh')
    assert {tuple(c) for c in mesh.colors.tolist()} == {(65, 135, 205, 255)}


@needs_tool
def test_face_colour_overrides_solid_colour(tmp_path):
    mesh = step_preview.mesh_step(BLOCK.with_name('colored_block.step'), tmp_path / 'model.mesh')
    colors = {tuple(c) for c in mesh.colors.tolist()}
    assert colors == {(0, 255, 0, 255), (255, 0, 0, 255)}
    assert 0 < (mesh.colors[:, 0] == 255).sum() < len(mesh.colors) / 2


def test_translucent_faces_are_moved_last(tmp_path):
    path = tmp_path / 'model.mesh'
    points = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]]
    colors = [[9, 9, 9, 80]] * 3 + [[9, 9, 9, 255]] * 3
    write_mesh(path, points, [[0, 1, 2], [3, 4, 5]], colors=colors)
    mesh = step_preview.read_mesh_file(path)
    assert mesh.faces.tolist() == [[3, 4, 5], [0, 1, 2]] and mesh.opaque_faces == 1


@needs_tool
def test_material_named_like_glazing_becomes_translucent(tmp_path):
    text = BLOCK.with_name('colored_block.step').read_text(encoding='ascii')
    assert text.count("COLOUR_RGB('',1.,0.,0.)") == 1
    source = tmp_path / 'glazed.step'
    source.write_text(text.replace("COLOUR_RGB('',1.,0.,0.)", "COLOUR_RGB('Polycarbonate (Tinted Black)',1.,0.,0.)"), encoding='ascii')
    mesh = step_preview.mesh_step(source, tmp_path / 'model.mesh')
    assert {tuple(c) for c in mesh.colors.tolist()} == {(0, 255, 0, 255), (255, 0, 0, 80)}
    assert 0 < mesh.opaque_faces < len(mesh.faces)
    assert (mesh.colors[mesh.faces[:mesh.opaque_faces, 0], 3] == 255).all()
    assert (mesh.colors[mesh.faces[mesh.opaque_faces:, 0], 3] == 80).all()


def test_cache_is_only_used_inside_a_preview_job(tmp_path):
    job = tmp_path / 'DracoConvPreview' / '{12345678-1234-1234-1234-123456789ABC}'
    assert step_preview._cache_dir(job / 'model.mesh') == tmp_path / 'DracoConvPreview' / 'mesh-cache'
    assert step_preview._cache_dir(tmp_path / 'model.mesh') is None


def test_cache_keeps_few_recent_meshes(tmp_path):
    names = ['%064x.mesh' % i for i in range(4)]
    for age, name in enumerate(names):
        (tmp_path / name).write_bytes(b'x')
        os.utime(tmp_path / name, (1000 - age, 1000 - age))
    (tmp_path / 'other.txt').write_bytes(b'kept')
    step_preview.prune_cache(tmp_path, now=1001)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(names[:2] + ['other.txt'])
    step_preview.prune_cache(tmp_path, now=1001 + step_preview.CACHE_SECONDS)
    assert [p.name for p in tmp_path.iterdir()] == ['other.txt']


@needs_tool
def test_second_reading_of_a_slow_file_comes_from_the_cache(tmp_path, monkeypatch):
    job = tmp_path / 'DracoConvPreview' / '{12345678-1234-1234-1234-123456789ABC}'
    job.mkdir(parents=True)
    monkeypatch.setattr(step_preview, 'CACHE_MIN_SECONDS', 0)
    first = step_preview.mesh_step(BLOCK, job / 'model.mesh')
    cached = list((tmp_path / 'DracoConvPreview' / 'mesh-cache').iterdir())
    assert len(cached) == 1 and not (job / 'model.mesh').exists()
    # Un outil qui échouerait à coup sûr : le résultat ne peut venir que du cache.
    again = step_preview.mesh_step(BLOCK, job / 'model.mesh', tool=Path(sys.executable))
    assert np.array_equal(first.faces, again.faces) and np.array_equal(first.colors, again.colors)
    cached[0].write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        step_preview.mesh_step(BLOCK, job / 'model.mesh', tool=Path(sys.executable))
    assert not cached[0].exists()


@needs_tool
def test_fast_readings_are_not_cached(tmp_path):
    job = tmp_path / 'DracoConvPreview' / '{12345678-1234-1234-1234-123456789ABC}'
    job.mkdir(parents=True)
    step_preview.mesh_step(BLOCK, job / 'model.mesh')
    assert not (tmp_path / 'DracoConvPreview' / 'mesh-cache').exists()
