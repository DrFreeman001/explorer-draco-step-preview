"""Lecture des maillages STL, OBJ et 3MF pour l'aperçu, reconnus par leur contenu et non par leur nom.

Lecteurs volontairement tolérants (fichiers d'impression 3D souvent imparfaits) mais bornés : taille d'entrée,
nombre de sommets et de faces, volume décompressé d'un 3MF. Les couleurs sont gardées quand le fichier en porte :
couleurs de faces des STL binaires (conventions VisCAM/SolidView et Materialise Magics), couleurs de sommets des
OBJ, matériaux et groupes de couleurs des 3MF.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from xml.etree import ElementTree

import numpy as np

from explorer_preview.preview_rendering import MAX_FACES, MAX_VERTICES, DisplayMesh, prepare_arrays

MAX_INPUT = 200 * 1024 * 1024
MAX_3MF_UNPACKED = 1024 * 1024 * 1024
DEFAULT_RGBA = (65, 135, 205, 255)

_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
_PROD_PATH = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path"
_MATERIAL = "{http://schemas.microsoft.com/3dmanufacturing/material/2015/02}"
class _Block:
    """Bloc <mesh>…</mesh> d'un document, présenté comme un résultat d'expression régulière (group 0 et 1)."""

    def __init__(self, data: bytes, begin: int, end: int):
        self.data, self.begin, self.end = data, begin, end

    def group(self, which: int) -> bytes:
        return self.data[self.begin:self.end + 7] if which == 0 else self.data[self.begin + 6:self.end]
# Sommets « x y z » dans cet ordre, triangles « v1 v2 v3 » : vérifié par comptage, sinon analyse XML complète.
_COORD = re.compile(rb'<vertex\s+x="([^"]*)"\s+y="([^"]*)"\s+z="([^"]*)"\s*/>')
_CORNER = re.compile(rb'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"\s*/>')


def binary_stl_count(head: bytes, size: int) -> int:
    """Nombre de triangles lisibles d'un STL binaire, 0 si ce n'en est pas un.

    Tolère un compte faux ou un fichier tronqué (vu sur des exports netfabb) : on garde les triangles complets.
    """
    if size < 134 or len(head) < 84:
        return 0
    count = struct.unpack_from("<I", head, 80)[0]
    if 84 + 50 * count == size:
        return count
    if (size - 84) % 50 == 0:
        return (size - 84) // 50
    if 0 < count and 84 + 50 * count < size:  # octets en trop après les triangles annoncés
        return count
    complete = (size - 84) // 50
    if count > complete and len(head) >= 134:
        # Fichier tronqué : accepté seulement si le premier triangle est fait de nombres finis et raisonnables.
        first = np.frombuffer(head, "<f4", 12, 84)
        if np.isfinite(first).all() and np.abs(first).max() < 1e7:
            return complete
    return 0


def _ascii_stl(head: bytes) -> bool:
    text = head.lstrip(b"\xef\xbb\xbf").lstrip()
    return text[:5].lower() == b"solid" and b"facet" in head.lower()


def detect(head: bytes, size: int) -> str | None:
    """'stl', '3mf' ou 'obj' d'après les premiers octets et la taille ; None si le contenu n'est aucun des trois."""
    if head.startswith(b"PK\x03\x04"):
        return "3mf"
    if _ascii_stl(head) or binary_stl_count(head, size):
        return "stl"
    if re.search(rb"(^|\n)\s*(v|f|o|g|mtllib|usemtl)\s", head):
        return "obj"
    return None


def _finish(triangles: np.ndarray, colors: np.ndarray | None) -> DisplayMesh:
    """triangles (n, 3, 3) et couleurs RGBA par face (n, 4) ou None → maillage non indexé, une couleur par sommet."""
    count = len(triangles)
    if not 0 < count <= MAX_FACES or count * 3 > MAX_VERTICES:
        raise ValueError("Mesh is empty or exceeds preview limit")
    mesh = prepare_arrays(triangles.reshape(-1, 3), np.arange(count * 3, dtype=np.uint32).reshape(-1, 3))
    if colors is not None and (colors != DEFAULT_RGBA).any():
        mesh.colors = np.ascontiguousarray(np.repeat(colors.astype(np.uint8), 3, axis=0))
        translucent = colors[:, 3] < 255
        if translucent.any():
            order = np.argsort(translucent, kind="stable")
            mesh.faces = np.ascontiguousarray(mesh.faces[order])
            mesh.opaque_faces = int(count - translucent.sum())
    return mesh


# -- STL ------------------------------------------------------------------------------------------------------

def _stl_binary_colors(header: bytes, attributes: np.ndarray) -> np.ndarray | None:
    magics = header.find(b"COLOR=")
    rgba = np.empty((len(attributes), 4), np.uint8)
    rgba[:, 3] = 255
    five = lambda shift: (((attributes >> shift) & 31) * 255 // 31).astype(np.uint8)  # noqa: E731
    if magics >= 0 and magics + 10 <= len(header):
        # Materialise Magics : rouge en bits 0-4, bit 15 à 0 pour une couleur propre à la face.
        default = np.frombuffer(header, np.uint8, 4, magics + 6)
        own = (attributes & 0x8000) == 0
        rgba[:] = default
        rgba[:, 3] = 255
        rgba[own, 0], rgba[own, 1], rgba[own, 2] = five(0)[own], five(5)[own], five(10)[own]
        return rgba
    own = (attributes & 0x8000) != 0
    if not own.any():
        return None
    # VisCAM / SolidView : bleu en bits 0-4, bit 15 à 1 pour une couleur valide.
    rgba[:] = DEFAULT_RGBA
    rgba[own, 0], rgba[own, 1], rgba[own, 2] = five(10)[own], five(5)[own], five(0)[own]
    return rgba


def load_stl(data: bytes) -> DisplayMesh:
    count = 0 if _ascii_stl(data[:4096]) else binary_stl_count(data[:4096], len(data))
    if count:
        record = np.dtype([("normal", "<f4", 3), ("points", "<f4", (3, 3)), ("attribute", "<u2")])
        faces = np.frombuffer(data, record, count, 84)
        return _finish(np.ascontiguousarray(faces["points"]), _stl_binary_colors(data[:80], faces["attribute"]))
    # ASCII, tolérant : plusieurs solides, virgules décimales, « endsolid » manquant, fin tronquée.
    numbers = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data, flags=re.IGNORECASE)
    usable = len(numbers) // 3 * 3
    if not usable:
        raise ValueError("Invalid STL input")
    flat = b" ".join(b" ".join(triple) for triple in numbers[:usable]).replace(b",", b".")
    try:
        points = np.array(flat.split(), dtype=np.float64).astype(np.float32)
    except ValueError as exc:
        raise ValueError("Invalid STL coordinates") from exc
    return _finish(points.reshape(-1, 3, 3), None)


# -- OBJ ------------------------------------------------------------------------------------------------------

def load_obj(data: bytes) -> DisplayMesh:
    vertices: list[list[float]] = []
    vertex_colors: list[list[float] | None] = []
    corners: list[int] = []
    for raw in data.splitlines():
        line = raw.strip()
        if line.startswith(b"v "):
            values = line.split()[1:]
            try:
                numbers = [float(v) for v in values[:6]]
            except ValueError as exc:
                raise ValueError("Invalid OBJ vertex") from exc
            if len(numbers) < 3:
                raise ValueError("Invalid OBJ vertex")
            vertices.append(numbers[:3])
            vertex_colors.append(numbers[3:6] if len(numbers) == 6 else None)
            if len(vertices) > MAX_VERTICES:
                raise ValueError("OBJ exceeds preview limit")
        elif line.startswith(b"f "):
            ids = []
            for token in line.split()[1:]:
                index = int(token.split(b"/", 1)[0])
                ids.append(index - 1 if index > 0 else len(vertices) + index)
            for k in range(1, len(ids) - 1):  # éventail : polygone en triangles
                corners += (ids[0], ids[k], ids[k + 1])
            if len(corners) > 3 * MAX_FACES:
                raise ValueError("OBJ exceeds preview limit")
    if not vertices or not corners:
        raise ValueError("OBJ has no faces")
    points = np.asarray(vertices, np.float32)
    index = np.asarray(corners, np.int64)
    if index.min() < 0 or index.max() >= len(points):
        raise ValueError("Invalid OBJ face index")
    colors = None
    if all(c is not None for c in vertex_colors):
        per_vertex = np.asarray(vertex_colors, np.float64)
        if per_vertex.max() > 1.0:  # certains exports écrivent 0-255
            per_vertex = per_vertex / 255.0
        rgb = (np.clip(per_vertex[index.reshape(-1, 3)].mean(axis=1), 0, 1) * 255 + 0.5).astype(np.uint8)
        colors = np.concatenate([rgb, np.full((len(rgb), 1), 255, np.uint8)], axis=1)
    return _finish(points[index].reshape(-1, 3, 3), colors)


# -- 3MF ------------------------------------------------------------------------------------------------------

def _rgba(text: str | None) -> tuple[int, int, int, int] | None:
    if not text or not text.startswith("#") or len(text) not in (7, 9):
        return None
    try:
        value = bytes.fromhex(text[1:])
    except ValueError:
        return None
    return (value[0], value[1], value[2], value[3] if len(value) == 4 else 255)


def _transform(text: str | None) -> np.ndarray:
    matrix = np.eye(4)
    if text:
        values = [float(v) for v in text.split()]
        if len(values) != 12:
            raise ValueError("Invalid 3MF transform")
        matrix[:, :3] = np.asarray(values).reshape(4, 3)
    return matrix


class _Package:
    def __init__(self, data: bytes):
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid 3MF archive") from exc
        self.names = {name.lower().lstrip("/"): name for name in self.zip.namelist()}
        self.unpacked = 0
        self.models: dict[str, tuple[dict, list]] = {}
        self.triangles: list[np.ndarray] = []
        self.colors: list[np.ndarray] = []
        self.faces = 0

    def root(self) -> str:
        rels = self.names.get("_rels/.rels")
        if rels:
            for element in ElementTree.fromstring(self._read(rels)).iter():
                if element.get("Type", "").endswith("/3dmodel") and element.get("Target"):
                    return element.get("Target").lstrip("/")
        return "3D/3dmodel.model"

    def _read(self, name: str) -> bytes:
        info = self.zip.getinfo(name)
        self.unpacked += info.file_size
        if self.unpacked > MAX_3MF_UNPACKED:
            raise ValueError("3MF unpacks beyond preview limit")
        return self.zip.read(name)

    def model(self, path: str) -> tuple[dict, list]:
        key = path.lower().lstrip("/")
        if key not in self.models:
            if key not in self.names:
                raise ValueError("3MF part is missing: " + path)
            self.models[key] = self._parse(self._read(self.names[key]))
        return self.models[key]

    def _parse(self, data: bytes) -> tuple[dict, list]:
        # Chemin rapide : les blocs <mesh> sans propriétés par triangle sont lus par expressions régulières et
        # remplacés par un repère avant l'analyse XML, qui ne voit plus que la structure (dix fois plus rapide).
        fast: list[tuple[np.ndarray, np.ndarray]] = []

        def take(match: _Block) -> bytes:
            block = match.group(1)
            if b'p1="' in block or b"pid=" in block:
                return match.group(0)
            split = block.find(b"<triangles")
            coords = _COORD.findall(block, 0, max(split, 0))
            corners = _CORNER.findall(block, max(split, 0))
            if (split < 0 or len(coords) != block.count(b"<vertex ", 0, split)
                    or len(corners) != block.count(b"<triangle ", split)):
                return match.group(0)
            try:
                points = np.array(coords).astype(np.float64).reshape(-1, 3)
                ids = np.array(corners).astype(np.int64).reshape(-1, 3)
            except ValueError:
                return match.group(0)
            fast.append((points, ids))
            return b'<mesh dcfast="%d"/>' % (len(fast) - 1)

        pieces, start = [], 0
        while (begin := data.find(b"<mesh>", start)) >= 0:
            end = data.find(b"</mesh>", begin)
            if end < 0:
                break
            pieces += (data[start:begin], take(_Block(data, begin, end)))
            start = end + 7
        data = b"".join(pieces) + data[start:] if pieces else data
        objects: dict[str, dict] = {}
        properties: dict[str, list] = {}
        build: list[tuple[str | None, str, np.ndarray]] = []
        current = None
        vertices: list[tuple[float, float, float]] = []
        triangles: list[tuple] = []
        for event, element in ElementTree.iterparse(io.BytesIO(data), events=("start", "end")):
            tag = element.tag
            if event == "start":
                if tag == _CORE + "object":
                    current = {"pid": element.get("pid"), "pindex": element.get("pindex"), "components": []}
                    vertices, triangles = [], []
                continue
            if tag == _CORE + "mesh" and element.get("dcfast") is not None and current is not None:
                current["vertices"], current["ids"] = fast[int(element.get("dcfast"))]
            elif tag == _CORE + "vertex":
                vertices.append((float(element.get("x")), float(element.get("y")), float(element.get("z"))))
            elif tag == _CORE + "triangle":
                triangles.append((int(element.get("v1")), int(element.get("v2")), int(element.get("v3")),
                                  element.get("pid"), element.get("p1")))
            elif tag == _CORE + "component" and current is not None:
                current["components"].append((element.get(_PROD_PATH), element.get("objectid"),
                                              _transform(element.get("transform"))))
            elif tag == _CORE + "object" and current is not None:
                if triangles:
                    current["vertices"] = np.asarray(vertices, np.float64)
                    current["ids"] = np.asarray([t[:3] for t in triangles], np.int64)
                    current["props"] = [t[3:] for t in triangles]
                objects[element.get("id")] = current
                current = None
            elif tag == _CORE + "basematerials":
                properties[element.get("id")] = [_rgba(b.get("displaycolor")) for b in element.findall(_CORE + "base")]
            elif tag == _MATERIAL + "colorgroup":
                properties[element.get("id")] = [_rgba(c.get("color")) for c in element.findall(_MATERIAL + "color")]
            elif tag == _CORE + "item":
                build.append((element.get(_PROD_PATH), element.get("objectid"), _transform(element.get("transform"))))
            if tag in (_CORE + "vertex", _CORE + "triangle"):
                element.clear()
        return {"objects": objects, "properties": properties}, build

    def place(self, path: str, object_id: str, matrix: np.ndarray, depth: int = 0) -> None:
        if depth > 16:
            raise ValueError("3MF components nest too deeply")
        model, _ = self.model(path)
        item = model["objects"].get(object_id)
        if item is None:
            raise ValueError("3MF object is missing: " + str(object_id))
        for sub_path, sub_id, sub_matrix in item["components"]:
            self.place(sub_path or path, sub_id, sub_matrix @ matrix, depth + 1)
        if "ids" not in item or not len(item["ids"]):
            return
        points = item["vertices"]
        points = (points @ matrix[:3, :3] + matrix[3, :3]).astype(np.float32)
        ids = item["ids"]
        if ids.min() < 0 or ids.max() >= len(points):
            raise ValueError("Invalid 3MF triangle index")
        self.faces += len(ids)
        if self.faces > MAX_FACES or self.faces * 3 > MAX_VERTICES:
            raise ValueError("3MF exceeds preview limit")
        properties = model["properties"]

        def color(pid, index):
            group = properties.get(pid)
            if group and index is not None and 0 <= int(index) < len(group) and group[int(index)]:
                return group[int(index)]
            return DEFAULT_RGBA

        rgba = np.tile(np.asarray(color(item["pid"], item["pindex"]), np.uint8), (len(ids), 1))
        for row, (pid, p1) in enumerate(item.get("props") or ()):
            if pid is not None or p1 is not None:
                rgba[row] = color(pid or item["pid"], p1 if p1 is not None else item["pindex"])
        self.triangles.append(points[ids])
        self.colors.append(rgba)


_UNITS_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}


def load_3mf(data: bytes) -> DisplayMesh:
    package = _Package(data)
    root = package.root()
    _, build = package.model(root)
    unit = re.search(rb'<model[^>]*\sunit="([a-z]+)"', package.zip.open(package.names[root.lower()]).read(4096))
    if not build:
        raise ValueError("3MF build is empty")
    for path, object_id, matrix in build:
        package.place(path or root, object_id, matrix)
    if not package.triangles:
        raise ValueError("3MF has no triangles")
    mesh = _finish(np.concatenate(package.triangles), np.concatenate(package.colors))
    mesh.unit_mm = _UNITS_MM.get(unit.group(1).decode() if unit else "millimeter", 1.0)
    return mesh


LOADERS = {"stl": load_stl, "obj": load_obj, "3mf": load_3mf}
