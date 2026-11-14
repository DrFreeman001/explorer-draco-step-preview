import base64
import io
import json
import struct
import zipfile

import DracoPy
import numpy as np
import pytest

from explorer_preview import mesh_formats as mf
from explorer_preview import scene_formats as sf

POINTS = np.array([[0, 0, 0], [2, 0, 0], [0, 4, 0], [0, 0, 8]], np.float32)
FACES = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)


def extent(mesh):
    return np.round(np.ptp(mesh.positions, axis=0) / np.ptp(mesh.positions, axis=0).max(), 4)


# -- PLY --

def ply_binary(quads=False):
    header = ("ply\nformat binary_little_endian 1.0\ncomment test\nelement vertex 4\nproperty float x\n"
              "property float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\n"
              "element face {}\nproperty list uchar int vertex_indices\nend_header\n").format(1 if quads else 2)
    body = b"".join(struct.pack("<3f3B", *p, 255, 0, 0) for p in POINTS)
    if quads:
        body += struct.pack("<B4i", 4, 0, 1, 2, 3)
    else:
        body += b"".join(struct.pack("<B3i", 3, *f) for f in FACES)
    return header.encode() + body


def test_ply_binary_with_vertex_colors():
    data = ply_binary()
    assert mf.detect(data[:4096], len(data)) == "ply"
    mesh = mf.LOADERS["ply"](data)
    assert len(mesh.faces) == 2 and mesh.colors[0].tolist() == [255, 0, 0, 255]
    assert mesh.size == (2.0, 4.0, 8.0)


def test_ply_polygons_and_ascii():
    assert len(sf.load_ply(ply_binary(quads=True)).faces) == 2
    text = b"ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\n" \
           b"element face 1\nproperty list uchar int vertex_index\nend_header\n0 0 0\n2 0 0\n2 4 0\n0 4 0\n4 0 1 2 3\n"
    mesh = sf.load_ply(text)
    assert len(mesh.faces) == 2 and mesh.colors is None
    with pytest.raises(ValueError):
        sf.load_ply(b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n")


# -- glTF --

def gltf(points=POINTS, faces=FACES, node=None, draco=False, embedded=False, material=None):
    if draco:
        blob = DracoPy.encode(points, faces)
        primitive = {"attributes": {"POSITION": 0}, "indices": 1,
                     "extensions": {"KHR_draco_mesh_compression": {"bufferView": 0, "attributes": {"POSITION": 0}}}}
        views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(blob)}]
        accessors = [{"componentType": 5126, "count": len(points), "type": "VEC3"},
                     {"componentType": 5125, "count": faces.size, "type": "SCALAR"}]
    else:
        blob = points.astype("<f4").tobytes() + faces.astype("<u4").tobytes()
        primitive = {"attributes": {"POSITION": 0}, "indices": 1}
        views = [{"buffer": 0, "byteOffset": 0, "byteLength": points.nbytes},
                 {"buffer": 0, "byteOffset": points.nbytes, "byteLength": faces.nbytes}]
        accessors = [{"bufferView": 0, "componentType": 5126, "count": len(points), "type": "VEC3"},
                     {"bufferView": 1, "componentType": 5125, "count": faces.size, "type": "SCALAR"}]
    if material is not None:
        primitive["material"] = 0
    document = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
                "nodes": [dict(node or {}, mesh=0)], "meshes": [{"primitives": [primitive]}],
                "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    if material is not None:
        document["materials"] = [material]
    if draco:
        document["extensionsUsed"] = ["KHR_draco_mesh_compression"]
    if embedded:
        document["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(blob).decode()
        return json.dumps(document).encode()
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    chunks = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def test_glb_is_turned_z_up_and_in_millimetres():
    data = gltf()
    assert mf.detect(data[:4096], len(data)) == "gltf"
    mesh = mf.LOADERS["gltf"](data)
    # glTF : Y vertical, en mètres → Z vertical, en millimètres ; la hauteur Y=4 devient Z.
    assert mesh.size == pytest.approx((2.0, 8.0, 4.0)) and mesh.unit_mm == 1000.0


def test_gltf_embedded_node_transform_and_material():
    material = {"pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 0.5]}, "alphaMode": "BLEND"}
    data = gltf(node={"translation": [10, 0, 0], "scale": [1, 2, 1]}, embedded=True, material=material)
    assert mf.detect(data[:4096], len(data)) == "gltf"
    mesh = sf.load_gltf(data)
    assert mesh.size == pytest.approx((2.0, 8.0, 8.0))
    assert mesh.colors[0].tolist() == [255, 0, 0, 128] and mesh.opaque_faces == 0


def test_gltf_draco_compressed():
    mesh = sf.load_gltf(gltf(draco=True))
    assert len(mesh.faces) == 2 and mesh.size == pytest.approx((2.0, 8.0, 4.0), rel=1e-3)  # Draco quantifie


def test_gltf_external_buffer_is_refused():
    document = {"asset": {"version": "2.0"}, "buffers": [{"uri": "model.bin", "byteLength": 4}]}
    with pytest.raises(ValueError, match="external"):
        sf.load_gltf(json.dumps(document).encode())


# -- AMF --

AMF = b"""<?xml version="1.0"?>
<amf unit="inch">
 <material id="2"><color><r>0</r><g>1</g><b>0</b></color></material>
 <object id="1"><mesh>
  <vertices>
   <vertex><coordinates><x>0</x><y>0</y><z>0</z></coordinates></vertex>
   <vertex><coordinates><x>2</x><y>0</y><z>0</z></coordinates></vertex>
   <vertex><coordinates><x>0</x><y>4</y><z>0</z></coordinates></vertex>
   <vertex><coordinates><x>0</x><y>0</y><z>8</z></coordinates></vertex>
  </vertices>
  <volume materialid="2"><triangle><v1>0</v1><v2>1</v2><v3>2</v3></triangle></volume>
  <volume><color><r>1</r><g>0</g><b>0</b></color><triangle><v1>0</v1><v2>2</v2><v3>3</v3></triangle></volume>
 </mesh></object>
 <constellation id="3">
  <instance objectid="1"><deltax>0</deltax><deltay>0</deltay><deltaz>0</deltaz></instance>
  <instance objectid="1"><deltax>20</deltax><deltay>0</deltay><deltaz>0</deltaz><rz>90</rz></instance>
 </constellation>
</amf>"""


def test_amf_colors_units_and_instances():
    assert mf.detect(AMF[:4096], len(AMF)) == "amf"
    mesh = sf.load_amf(AMF)
    assert len(mesh.faces) == 4 and mesh.unit_mm == 25.4
    assert {tuple(c) for c in mesh.colors.tolist()} == {(0, 255, 0, 255), (255, 0, 0, 255)}
    assert mesh.size[0] == pytest.approx(20.0)  # seconde instance tournée de 90° (x de -4 à 0) puis décalée de 20


def test_zipped_amf_is_told_apart_from_3mf():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("model.amf", AMF)
    data = buffer.getvalue()
    assert mf.detect(data[:4096], len(data)) == "3mf" and sf.zip_kind(data) == "amf"
    assert len(mf.LOADERS["3mf"](data).faces) == 4
