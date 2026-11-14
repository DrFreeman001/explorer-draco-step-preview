import io
import struct
import zipfile

import numpy as np
import pytest

from explorer_preview import mesh_formats as mf

TRIS = np.array([[[0, 0, 0], [2, 0, 0], [0, 4, 0]], [[0, 0, 0], [0, 4, 0], [0, 0, 8]]], np.float32)


def binary_stl(triangles=TRIS, attributes=(0, 0), header=b""):
    out = bytearray(header.ljust(80, b" ")[:80]) + struct.pack("<I", len(triangles))
    for tri, attr in zip(triangles, attributes):
        out += struct.pack("<3f", 0, 0, 1) + tri.astype("<f4").tobytes() + struct.pack("<H", attr)
    return bytes(out)


def extent(mesh):
    return np.ptp(mesh.positions, axis=0)


def test_detect_by_content():
    stl = binary_stl()
    assert mf.detect(stl[:4096], len(stl)) == "stl"
    assert mf.detect(b"solid x\n facet normal 0 0 1\n", 40) == "stl"
    assert mf.detect(b"# blender\nv 0 0 0\nv 1 0 0\n", 30) == "obj"
    assert mf.detect(b"PK\x03\x04rest", 100) == "3mf"
    assert mf.detect(b"DRACO\x02\x02", 50) is None
    assert mf.detect(b"ISO-10303-21;", 50) is None


def test_binary_stl_keeps_every_triangle_without_colors():
    mesh = mf.load_stl(binary_stl())
    assert len(mesh.faces) == 2 and mesh.colors is None
    assert np.allclose(extent(mesh) / extent(mesh).max(), [0.25, 0.5, 1.0])


def test_binary_stl_viscam_colors():
    red = 0x8000 | (31 << 10)  # VisCAM : bit 15 = couleur valide, rouge en bits 10-14
    mesh = mf.load_stl(binary_stl(attributes=(red, 0)))
    assert mesh.colors[:3].tolist() == [[255, 0, 0, 255]] * 3
    assert mesh.colors[3:].tolist() == [list(mf.DEFAULT_RGBA)] * 3


def test_binary_stl_magics_colors():
    header = b"COLOR=" + bytes([10, 20, 30, 255])
    green = 31 << 5  # Magics : bit 15 à 0 = couleur propre, rouge en bits 0-4
    mesh = mf.load_stl(binary_stl(attributes=(green, 0x8000), header=header))
    assert mesh.colors[0].tolist() == [0, 255, 0, 255]
    assert mesh.colors[3].tolist() == [10, 20, 30, 255]


def test_ascii_stl_is_tolerant():
    text = ("﻿solid a\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 4 0\nendloop\nendfacet\n"
            "endsolid a\nsolid b\nfacet normal 0 0 1\nouter loop\nvertex 0,0 0,0 0,0\nVERTEX 0 4 0\nvertex 0 0 8\n"
            "endloop\nendfacet\nfacet normal 0 0 1\nouter loop\nvertex 1 1 1\n").encode("utf-8")
    mesh = mf.load_stl(text)
    assert len(mesh.faces) == 2  # le troisième triangle, tronqué, est ignoré
    with pytest.raises(ValueError):
        mf.load_stl(b"solid empty\nendsolid empty\n")


def test_obj_polygons_negative_indices_and_colors():
    text = b"""# test
v 0 0 0 1 0 0
v 2 0 0 1 0 0
v 2 4 0 1 0 0
v 0 4 0 1 0 0
vt 0 0
f 1/1/1 2/1/1 3/1/1 4/1/1
f -4 -2 -1
"""
    mesh = mf.load_obj(text)
    assert len(mesh.faces) == 3
    assert mesh.colors[0].tolist() == [255, 0, 0, 255]
    plain = mf.load_obj(b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    assert plain.colors is None
    with pytest.raises(ValueError):
        mf.load_obj(b"v 0 0 0\nv 1 0 0\nf 1 2 9\n")
    with pytest.raises(ValueError):
        mf.load_obj(b"v 0 0 0\n")


CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def three_mf(parts):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return buffer.getvalue()


ROOT = f"""<?xml version="1.0"?>
<model xmlns="{CORE}" xmlns:p="{PROD}" unit="millimeter">
 <resources>
  <basematerials id="5"><base name="red" displaycolor="#FF0000"/><base name="glass" displaycolor="#00FF0080"/></basematerials>
  <object id="1" type="model" pid="5" pindex="0">
   <mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="0"/></vertices>
   <triangles><triangle v1="0" v2="1" v3="2"/><triangle v1="0" v2="2" v3="1" pid="5" p1="1"/></triangles></mesh>
  </object>
  <object id="2" type="model"><components><component p:path="/3D/Objects/part.model" objectid="7" transform="1 0 0 0 1 0 0 0 1 0 0 30"/></components></object>
 </resources>
 <build><item objectid="1"/><item objectid="2" transform="1 0 0 0 1 0 0 0 1 100 0 0"/></build>
</model>"""
PART = f"""<?xml version="1.0"?>
<model xmlns="{CORE}"><resources><object id="7"><mesh>
 <vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/></vertices>
 <triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources><build/></model>"""


def test_3mf_build_components_transforms_and_colors():
    mesh = mf.load_3mf(three_mf({"3D/3dmodel.model": ROOT, "3D/Objects/part.model": PART}))
    assert len(mesh.faces) == 3
    assert mesh.opaque_faces == 2  # le triangle « verre » translucide passe en dernier
    assert {tuple(c) for c in mesh.colors.tolist()} == {(255, 0, 0, 255), (0, 255, 0, 128), mf.DEFAULT_RGBA}
    assert np.isclose(extent(mesh)[0] / extent(mesh)[2], 101 / 30, rtol=1e-3)


def test_3mf_errors_are_reported():
    with pytest.raises(ValueError):
        mf.load_3mf(b"PK\x03\x04 not a zip")
    with pytest.raises(ValueError, match="missing"):
        mf.load_3mf(three_mf({"3D/3dmodel.model": ROOT}))


def test_3mf_unpacked_size_is_bounded(monkeypatch):
    monkeypatch.setattr(mf, "MAX_3MF_UNPACKED", 100)
    with pytest.raises(ValueError, match="limit"):
        mf.load_3mf(three_mf({"3D/3dmodel.model": ROOT, "3D/Objects/part.model": PART}))


def test_load_model_routes_new_formats(tmp_path):
    from explorer_preview import shell_preview

    path = tmp_path / "input.drc"
    path.write_bytes(binary_stl())
    assert len(shell_preview.load_model(path).faces) == 2
    path.write_bytes(three_mf({"3D/3dmodel.model": ROOT, "3D/Objects/part.model": PART}))
    assert len(shell_preview.load_model(path).faces) == 3
    path.write_bytes(b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    assert len(shell_preview.load_model(path).faces) == 1


def test_truncated_binary_stl_keeps_complete_triangles():
    data = binary_stl()
    lying = data[:80] + struct.pack("<I", 1000) + data[84:]  # compte faux, fichier « tronqué »
    assert mf.detect(lying[:4096], len(lying)) == "stl"
    assert len(mf.load_stl(lying).faces) == 2
    assert len(mf.load_stl(data + b"\0" * 7).faces) == 2  # octets en trop après les triangles


def test_stl_cut_mid_triangle_and_garbage():
    data = binary_stl()
    cut = data[:80] + struct.pack("<I", 9) + data[84:-20]  # coupé au milieu du second triangle
    assert mf.detect(cut[:4096], len(cut)) == "stl" and len(mf.load_stl(cut).faces) == 1
    garbage = b"\x00" * 80 + struct.pack("<I", 9) + b"\xff" * 120
    assert mf.detect(garbage, len(garbage)) is None
