"""Lecture des maillages PLY, glTF (GLB et GLTF à données intégrées) et AMF pour l'aperçu.

Mêmes principes que mesh_formats : reconnaissance au contenu, lecture bornée, couleurs gardées quand le fichier en
porte. Le glTF compressé avec Draco (KHR_draco_mesh_compression) est décodé par DracoPy. Le glTF, dont l'axe vertical
est Y et l'unité le mètre, est remis à l'axe Z vertical et en millimètres, comme les modèles d'impression.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import struct
import zipfile
from xml.etree import ElementTree

import numpy as np

from explorer_preview.mesh_formats import DEFAULT_RGBA, MAX_3MF_UNPACKED, MAX_FACES, MAX_VERTICES, _finish

# -- PLY ------------------------------------------------------------------------------------------------------

_PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
              "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
              "float": "f4", "float32": "f4", "double": "f8", "float64": "f8"}


def _ply_header(data: bytes):
    end = data.find(b"end_header")
    if not data.startswith(b"ply") or end < 0:
        raise ValueError("Invalid PLY header")
    body = data.index(b"\n", end) + 1
    fmt, elements = None, []
    for line in data[:end].decode("ascii", "replace").splitlines()[1:]:
        words = line.split()
        if not words or words[0] in ("comment", "obj_info"):
            continue
        if words[0] == "format":
            fmt = words[1]
        elif words[0] == "element":
            elements.append((words[1], int(words[2]), []))
        elif words[0] == "property" and elements:
            if words[1] == "list":
                elements[-1][2].append((words[4], ("list", _PLY_TYPES[words[2]], _PLY_TYPES[words[3]])))
            else:
                elements[-1][2].append((words[2], _PLY_TYPES[words[1]]))
    if fmt not in ("ascii", "binary_little_endian", "binary_big_endian"):
        raise ValueError("Unsupported PLY format")
    return fmt, elements, body


def _ply_colors(vertex: np.ndarray, names, faces: np.ndarray, face_colors):
    if face_colors is not None:
        rgb = face_colors
    elif all(n in names for n in ("red", "green", "blue")):
        per_vertex = np.stack([vertex[n] for n in ("red", "green", "blue")], axis=1).astype(np.float64)
        if per_vertex.max(initial=0) <= 1.0 and vertex["red"].dtype.kind == "f":
            per_vertex *= 255
        rgb = per_vertex[faces].mean(axis=1)
    else:
        return None
    rgba = np.empty((len(rgb), 4), np.uint8)
    rgba[:, :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    rgba[:, 3] = 255
    return rgba


def load_ply(data: bytes):
    fmt, elements, offset = _ply_header(data)
    endian = ">" if fmt == "binary_big_endian" else "<"
    vertex = faces = face_colors = None
    names: list[str] = []
    text = data[offset:].split() if fmt == "ascii" else None
    cursor = 0
    for name, count, props in elements:
        if count < 0 or count > 3 * MAX_FACES:
            raise ValueError("PLY exceeds preview limit")
        scalar = [(n, t) for n, t in props if not isinstance(t, tuple)]
        lists = [(n, t) for n, t in props if isinstance(t, tuple)]
        if fmt == "ascii":
            rows = []
            for _ in range(count):
                row, values = [], []
                for prop, kind in props:
                    if isinstance(kind, tuple):
                        size = int(text[cursor]); row.append(np.asarray(text[cursor + 1:cursor + 1 + size], np.int64))
                        cursor += 1 + size
                    else:
                        values.append(float(text[cursor])); cursor += 1
                rows.append((values, row))
            if name == "vertex":
                table = np.asarray([v for v, _ in rows], np.float64).reshape(count, len(scalar))
                vertex = {n: table[:, i] for i, (n, _) in enumerate(scalar)}
                names = [n for n, _ in scalar]
            elif name == "face":
                polygons = [r[0] for _, r in rows if r]
                faces = _fan(polygons)
        else:
            if not lists:
                dtype = np.dtype([(n, endian + t) for n, t in scalar])
                table = np.frombuffer(data, dtype, count, offset)
                offset += dtype.itemsize * count
                if name == "vertex":
                    vertex, names = table, list(table.dtype.names)
                continue
            # Faces : chemin rapide si toutes les listes ont trois sommets, sinon lecture face par face.
            fields = []
            for n, t in props:
                if isinstance(t, tuple):
                    fields += [(n + "_n", endian + t[1]), (n, endian + t[2], (3,))]
                else:
                    fields.append((n, endian + t))
            dtype = np.dtype(fields)
            table = np.frombuffer(data, dtype, count, offset) if offset + dtype.itemsize * count <= len(data) else None
            list_name = lists[0][0]
            if table is not None and (table[list_name + "_n"] == 3).all():
                offset += dtype.itemsize * count
                if name == "face":
                    faces = table[list_name].astype(np.int64)
                    if all(c in table.dtype.names for c in ("red", "green", "blue")):
                        face_colors = np.stack([table[c] for c in ("red", "green", "blue")], axis=1).astype(np.float64)
                continue
            polygons = []
            for _ in range(count):
                for n, t in props:
                    if isinstance(t, tuple):
                        size_type, index_type = np.dtype(endian + t[1]), np.dtype(endian + t[2])
                        size = int(np.frombuffer(data, size_type, 1, offset)[0]); offset += size_type.itemsize
                        polygons.append(np.frombuffer(data, index_type, size, offset).astype(np.int64))
                        offset += index_type.itemsize * size
                    else:
                        offset += np.dtype(t).itemsize
            if name == "face":
                faces = _fan(polygons)
    if vertex is None or faces is None or not len(faces):
        raise ValueError("PLY has no faces")
    points = np.stack([np.asarray(vertex[c], np.float64) for c in ("x", "y", "z")], axis=1).astype(np.float32)
    if faces.min() < 0 or faces.max() >= len(points):
        raise ValueError("Invalid PLY face index")
    return _finish(points[faces], _ply_colors(vertex, names, faces, face_colors))


def _fan(polygons) -> np.ndarray:
    triangles = [(p[0], p[k], p[k + 1]) for p in polygons for k in range(1, len(p) - 1)]
    if len(triangles) > MAX_FACES:
        raise ValueError("PLY exceeds preview limit")
    return np.asarray(triangles, np.int64).reshape(-1, 3)


# -- glTF -----------------------------------------------------------------------------------------------------

_COMPONENTS = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_Y_UP_TO_Z_UP = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], np.float64)


def _gltf_parts(data: bytes):
    if data[:4] == b"glTF":
        version, total = struct.unpack_from("<II", data, 4)
        if version != 2 or total > len(data):
            raise ValueError("Unsupported glTF binary")
        offset, document, binary = 12, None, b""
        while offset + 8 <= total:
            size, kind = struct.unpack_from("<II", data, offset)
            chunk = data[offset + 8:offset + 8 + size]
            if kind == 0x4E4F534A:
                document = json.loads(chunk)
            elif kind == 0x004E4942:
                binary = chunk
            offset += 8 + size + (-size % 4)
        if document is None:
            raise ValueError("glTF binary has no JSON chunk")
        return document, binary
    return json.loads(data.decode("utf-8-sig")), b""


def _buffers(document, binary: bytes) -> list[bytes]:
    buffers = []
    for index, buffer in enumerate(document.get("buffers", [])):
        uri = buffer.get("uri")
        if uri is None:
            buffers.append(binary)
        elif uri.startswith("data:") and ";base64," in uri:
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            raise ValueError("glTF external buffers are not supported in previews: " + uri[:60])
    return buffers


def _view(document, buffers, index: int) -> tuple[bytes, int, int | None]:
    view = document["bufferViews"][index]
    data = buffers[view["buffer"]]
    start = view.get("byteOffset", 0)
    return data[start:start + view["byteLength"]], 0, view.get("byteStride")


def _accessor(document, buffers, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    if "sparse" in accessor:
        raise ValueError("glTF sparse accessors are not supported")
    width = _WIDTH[accessor["type"]]
    component = np.dtype("<" + _COMPONENTS[accessor["componentType"]])
    count = accessor["count"]
    if count > 3 * MAX_FACES:
        raise ValueError("glTF exceeds preview limit")
    raw, _, stride = _view(document, buffers, accessor["bufferView"])
    start = accessor.get("byteOffset", 0)
    item = component.itemsize * width
    stride = stride or item
    if start + stride * (count - 1) + item > len(raw):
        raise ValueError("glTF accessor exceeds its buffer")
    values = np.lib.stride_tricks.as_strided(np.frombuffer(raw, np.uint8, len(raw) - start, start),
                                             (count, item), (stride, 1)).copy()
    values = values.view(component).reshape(count, width)
    if accessor.get("normalized") and component.kind in "iu":
        values = values.astype(np.float64) / np.iinfo(component).max
    return values


def _node_matrix(node) -> np.ndarray:
    if "matrix" in node:
        return np.asarray(node["matrix"], np.float64).reshape(4, 4)  # glTF : colonnes, soit une matrice pour v @ M
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    rotation = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                         [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                         [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation * np.asarray(node.get("scale", (1, 1, 1)), np.float64)[:, None]
    matrix[3, :3] = node.get("translation", (0, 0, 0))
    return matrix


def _primitive(document, buffers, primitive) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    draco = primitive.get("extensions", {}).get("KHR_draco_mesh_compression")
    if draco:
        import DracoPy

        raw, _, _ = _view(document, buffers, draco["bufferView"])
        decoded = DracoPy.decode(raw)
        points = np.asarray(decoded.points, np.float64)
        faces = np.asarray(decoded.faces, np.int64).reshape(-1, 3)
        colors = getattr(decoded, "colors", None)
        return points, faces, None if colors is None or not len(colors) else np.asarray(colors)
    if primitive.get("mode", 4) != 4:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), None
    attributes = primitive["attributes"]
    points = _accessor(document, buffers, attributes["POSITION"]).astype(np.float64)
    if "indices" in primitive:
        faces = _accessor(document, buffers, primitive["indices"]).astype(np.int64).reshape(-1, 3)
    else:
        faces = np.arange(len(points) // 3 * 3, dtype=np.int64).reshape(-1, 3)
    colors = None
    if "COLOR_0" in attributes:
        colors = _accessor(document, buffers, attributes["COLOR_0"]).astype(np.float64)
        if colors.max(initial=0) <= 1.0:
            colors = colors * 255
    return points, faces, colors


def load_gltf(data: bytes):
    document, binary = _gltf_parts(data)
    buffers = _buffers(document, binary)
    materials = document.get("materials", [])
    triangles, colors, faces_total = [], [], 0
    mesh_cache: dict[int, list] = {}

    def material_rgba(index):
        if index is None or index >= len(materials):
            return DEFAULT_RGBA
        factor = materials[index].get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        linear = np.clip(np.asarray(factor[:3], np.float64), 0, 1)
        srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
        alpha = factor[3] if materials[index].get("alphaMode") == "BLEND" else 1.0
        return tuple(int(v * 255 + 0.5) for v in (*srgb, alpha))

    def visit(node_index: int, parent: np.ndarray, depth: int) -> None:
        nonlocal faces_total
        if depth > 64:
            raise ValueError("glTF nodes nest too deeply")
        node = document["nodes"][node_index]
        matrix = _node_matrix(node) @ parent
        if "mesh" in node:
            primitives = mesh_cache.setdefault(node["mesh"], [
                (*_primitive(document, buffers, p), p.get("material")) for p in document["meshes"][node["mesh"]]["primitives"]])
            for points, faces, vertex_colors, material in primitives:
                if not len(faces):
                    continue
                if faces.min() < 0 or faces.max() >= len(points):
                    raise ValueError("Invalid glTF index")
                faces_total += len(faces)
                if faces_total > MAX_FACES or faces_total * 3 > MAX_VERTICES:
                    raise ValueError("glTF exceeds preview limit")
                placed = np.c_[points, np.ones(len(points))] @ matrix
                triangles.append(placed[:, :3].astype(np.float32)[faces])
                rgba = np.tile(np.asarray(material_rgba(material), np.uint8), (len(faces), 1))
                if vertex_colors is not None:
                    rgba[:, :3] = np.clip(vertex_colors[faces][:, :, :3].mean(axis=1) + 0.5, 0, 255).astype(np.uint8)
                colors.append(rgba)
        for child in node.get("children", []):
            visit(child, matrix, depth + 1)

    scenes = document.get("scenes")
    if scenes:
        roots = scenes[document.get("scene", 0)].get("nodes", [])
    else:
        children = {c for n in document.get("nodes", []) for c in n.get("children", [])}
        roots = [i for i in range(len(document.get("nodes", []))) if i not in children]
    for root in roots:
        visit(root, _Y_UP_TO_Z_UP, 0)
    if not triangles:
        raise ValueError("glTF has no triangles")
    mesh = _finish(np.concatenate(triangles), np.concatenate(colors))
    mesh.unit_mm = 1000.0  # glTF : mètres
    return mesh


# -- AMF ------------------------------------------------------------------------------------------------------

_AMF_UNITS_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "feet": 304.8,
                 "foot": 304.8, "meter": 1000.0}


def _amf_color(element) -> tuple[int, int, int, int] | None:
    color = element.find("color") if element is not None else None
    if color is None:
        return None
    try:
        values = [float(color.findtext(c, "1")) for c in ("r", "g", "b", "a")]
    except ValueError:
        return None
    return tuple(int(min(max(v, 0), 1) * 255 + 0.5) for v in values)


def load_amf(data: bytes):
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            inner = next((i for i in archive.infolist() if i.filename.lower().endswith(".amf")), archive.infolist()[0])
            if inner.file_size > MAX_3MF_UNPACKED:
                raise ValueError("AMF unpacks beyond preview limit")
            data = archive.read(inner)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError("Invalid AMF document") from exc
    materials = {m.get("id"): _amf_color(m) for m in root.findall("material")}
    objects = {}
    for obj in root.findall("object"):
        coords = obj.findall("mesh/vertices/vertex/coordinates")
        points = np.asarray([[float(c.findtext(a)) for a in ("x", "y", "z")] for c in coords], np.float64)
        object_color = _amf_color(obj)
        parts = []
        for volume in obj.findall("mesh/volume"):
            color = _amf_color(volume) or materials.get(volume.get("materialid")) or object_color or DEFAULT_RGBA
            ids = np.asarray([[int(t.findtext(v)) for v in ("v1", "v2", "v3")] for t in volume.findall("triangle")], np.int64)
            if len(ids):
                parts.append((ids.reshape(-1, 3), color))
        objects[obj.get("id")] = (points, parts)
    instances = [(i.get("objectid"), i) for c in root.findall("constellation") for i in c.findall("instance")]
    if not instances:
        instances = [(object_id, None) for object_id in objects]
    triangles, colors, total = [], [], 0
    for object_id, instance in instances:
        if object_id not in objects:
            raise ValueError("AMF object is missing: " + str(object_id))
        points, parts = objects[object_id]
        if instance is not None:
            angles = [math.radians(float(instance.findtext(a, "0"))) for a in ("rx", "ry", "rz")]
            rx = np.array([[1, 0, 0], [0, math.cos(angles[0]), -math.sin(angles[0])], [0, math.sin(angles[0]), math.cos(angles[0])]])
            ry = np.array([[math.cos(angles[1]), 0, math.sin(angles[1])], [0, 1, 0], [-math.sin(angles[1]), 0, math.cos(angles[1])]])
            rz = np.array([[math.cos(angles[2]), -math.sin(angles[2]), 0], [math.sin(angles[2]), math.cos(angles[2]), 0], [0, 0, 1]])
            delta = [float(instance.findtext(a, "0")) for a in ("deltax", "deltay", "deltaz")]
            points = points @ (rz @ ry @ rx).T + delta
        for ids, color in parts:
            if ids.min() < 0 or ids.max() >= len(points):
                raise ValueError("Invalid AMF triangle index")
            total += len(ids)
            if total > MAX_FACES:
                raise ValueError("AMF exceeds preview limit")
            triangles.append(points.astype(np.float32)[ids])
            colors.append(np.tile(np.asarray(color, np.uint8), (len(ids), 1)))
    if not triangles:
        raise ValueError("AMF has no triangles")
    mesh = _finish(np.concatenate(triangles), np.concatenate(colors))
    mesh.unit_mm = _AMF_UNITS_MM.get(root.get("unit", "millimeter"), 1.0)
    return mesh


def detect(head: bytes) -> str | None:
    if head.startswith(b"ply\n") or head.startswith(b"ply\r\n"):
        return "ply"
    if head[:4] == b"glTF":
        return "gltf"
    text = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if text.startswith(b"{") and b'"asset"' in head:
        return "gltf"
    if re.search(rb"<amf[\s>]", head[:2048]):
        return "amf"
    return None


def zip_kind(data: bytes) -> str:
    """Archive ZIP : AMF compressé si elle ne contient qu'un .amf, 3MF sinon."""
    try:
        names = [n.lower() for n in zipfile.ZipFile(io.BytesIO(data)).namelist()]
    except zipfile.BadZipFile:
        return "3mf"
    return "amf" if any(n.endswith(".amf") for n in names) and not any(n.endswith(".model") for n in names) else "3mf"
