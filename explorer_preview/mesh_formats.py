"""Lecture des maillages STL, OBJ et 3MF pour l'aperçu, reconnus par leur contenu et non par leur nom.

Lecteurs volontairement tolérants (fichiers d'impression 3D souvent imparfaits) mais bornés : taille d'entrée,
nombre de sommets et de faces, volume décompressé d'un 3MF. Les couleurs sont gardées quand le fichier en porte :
couleurs de faces des STL binaires (conventions VisCAM/SolidView et Materialise Magics), couleurs de sommets des
OBJ, matériaux et groupes de couleurs des 3MF.
"""
from __future__ import annotations

import io
import json
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
_CORNER = re.compile(rb'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"'
                     rb'(?:\s+(?:paint_color|slic3rpe:mmu_segmentation)="([0-9A-Fa-f]*)")?\s*/>')
_SLIC3R_PAINT = "{http://schemas.slic3r.org/3mf/2017/06}mmu_segmentation"


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


_PRINTABLE = frozenset(range(32, 127)) | {9, 10, 13}
_OBJ_LINE = re.compile(rb"(^|\n)\s*(v|f|o|g|mtllib|usemtl)\s")


def _is_text(head: bytes) -> bool:
    """Vrai pour un début de fichier texte (OBJ, STL texte…) : aucun octet nul, presque tout imprimable.

    Un STL binaire contient des nombres à virgule flottante, donc des octets nuls ou non imprimables.
    """
    if not head or b"\0" in head:
        return False
    printable = sum(1 for b in head if b in _PRINTABLE or b >= 0x80)  # UTF-8 accepté
    return printable >= 0.98 * len(head)


def detect(head: bytes, size: int) -> str | None:
    """'stl', '3mf', 'obj', 'ply', 'gltf' ou 'amf' d'après les premiers octets et la taille ; None sinon."""
    from explorer_preview import scene_formats

    if head.startswith(b"PK\x03\x04"):
        return "3mf"  # 3MF, ou AMF compressé : tranché à la lecture (load_zip)
    kind = scene_formats.detect(head)
    if kind:
        return kind
    if _ascii_stl(head):
        return "stl"
    # Un OBJ est du texte : le reconnaître avant le STL binaire, dont la lecture tolérante (fichiers tronqués)
    # prendrait sinon certains fichiers texte pour des triangles.
    if _is_text(head) and _OBJ_LINE.search(head):
        return "obj"
    if binary_stl_count(head, size):
        return "stl"
    if _OBJ_LINE.search(head):
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
        self.filaments, self.extruders = self._slicer_colors()

    def _slicer_colors(self):
        """Projets Bambu Studio, OrcaSlicer et PrusaSlicer : couleurs des filaments et extrudeur de chaque objet et pièce.

        Renvoie (couleurs RGBA par extrudeur, à partir de 1 ; {objet: (extrudeur, {pièce: extrudeur})}).
        """
        filaments: list[tuple[int, int, int, int]] = []
        for name in ("metadata/project_settings.config", "metadata/slic3r_pe.config"):
            if name not in self.names:
                continue
            text = self._read(self.names[name]).decode("utf-8", "replace")
            try:
                values = json.loads(text).get("filament_colour") or []
            except ValueError:  # PrusaSlicer : lignes « ; filament_colour = #RRGGBB;#RRGGBB »
                found = re.search(r"filament_colour\s*=\s*([^\r\n]*)", text)
                values = found.group(1).split(";") if found else []
            filaments = [c for c in (_rgba(v.strip()[:9]) for v in values) if c]
            break
        extruders: dict[str, tuple[int | None, dict[str, int]]] = {}
        for name in ("metadata/model_settings.config", "metadata/slic3r_pe_model.config"):
            if name not in self.names:
                continue
            try:
                root = ElementTree.fromstring(self._read(self.names[name]))
            except ElementTree.ParseError:
                break
            for obj in root.iter("object"):
                own = _extruder(obj)
                parts = {p.get("id"): e for p in obj.iter("part") if (e := _extruder(p))}
                parts.update({v.get("firstid"): e for v in obj.iter("volume") if (e := _extruder(v))})
                extruders[obj.get("id")] = (own, parts)
            break
        return filaments, extruders

    def filament(self, extruder: int | None) -> tuple[int, int, int, int] | None:
        if not self.filaments:
            return None
        index = (extruder or 1) - 1
        return self.filaments[index] if 0 <= index < len(self.filaments) else self.filaments[0]

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
                ids = np.array([c[:3] for c in corners]).astype(np.int64).reshape(-1, 3)
            except ValueError:
                return match.group(0)
            paint = [(row, c[3].decode()) for row, c in enumerate(corners) if c[3]] if b"paint" in block or b"mmu_" in block else []
            fast.append((points, ids, paint))
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
                current["vertices"], current["ids"], current["paint"] = fast[int(element.get("dcfast"))]
            elif tag == _CORE + "vertex":
                vertices.append((float(element.get("x")), float(element.get("y")), float(element.get("z"))))
            elif tag == _CORE + "triangle":
                triangles.append((int(element.get("v1")), int(element.get("v2")), int(element.get("v3")),
                                  element.get("pid"), element.get("p1"),
                                  element.get("paint_color") or element.get(_SLIC3R_PAINT)))
            elif tag == _CORE + "component" and current is not None:
                current["components"].append((element.get(_PROD_PATH), element.get("objectid"),
                                              _transform(element.get("transform"))))
            elif tag == _CORE + "object" and current is not None:
                if triangles:
                    current["vertices"] = np.asarray(vertices, np.float64)
                    current["ids"] = np.asarray([t[:3] for t in triangles], np.int64)
                    current["props"] = [t[3:5] for t in triangles]
                    current["paint"] = [(row, t[5]) for row, t in enumerate(triangles) if t[5]]
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

    def place(self, path: str, object_id: str, matrix: np.ndarray, depth: int = 0,
              extruder: int | None = None, top: str | None = None) -> None:
        if depth > 16:
            raise ValueError("3MF components nest too deeply")
        model, _ = self.model(path)
        item = model["objects"].get(object_id)
        if item is None:
            raise ValueError("3MF object is missing: " + str(object_id))
        if top is None:  # objet du plateau : son extrudeur vaut pour ses pièces sans réglage propre
            top = object_id
            extruder = self.extruders.get(object_id, (None, {}))[0]
        parts = self.extruders.get(top, (None, {}))[1]
        for sub_path, sub_id, sub_matrix in item["components"]:
            self.place(sub_path or path, sub_id, sub_matrix @ matrix, depth + 1, parts.get(sub_id) or extruder, top)
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

        base = color(item["pid"], item["pindex"])
        if base == DEFAULT_RGBA:  # pas de matériau 3MF : couleur du filament de l'extrudeur, si le trancheur la donne
            base = self.filament(parts.get(object_id) or extruder) or DEFAULT_RGBA
        rgba = np.tile(np.asarray(base, np.uint8), (len(ids), 1))
        for row, (pid, p1) in enumerate(item.get("props") or ()):
            if pid is not None or p1 is not None:
                rgba[row] = color(pid or item["pid"], p1 if p1 is not None else item["pindex"])
        if self.filaments:
            # Peinture multicolore du trancheur : couleur dominante de chaque triangle peint.
            for row, code in item.get("paint") or ():
                state = paint_state(code)
                if state:
                    rgba[row] = self.filament(state)
        self.triangles.append(points[ids])
        self.colors.append(rgba)


def _extruder(element) -> int | None:
    """Extrudeur d'un objet ou d'une pièce dans la configuration du trancheur ; None ou 0 : hérité."""
    for meta in element.findall("metadata"):
        if meta.get("key") == "extruder" or meta.get("type") == "volume" and meta.get("key") == "extruder":
            try:
                return int(meta.get("value")) or None
            except (TypeError, ValueError):
                return None
    return None


_PAINT_CACHE: dict[str, int] = {}


def paint_state(code: str) -> int:
    """État dominant d'un triangle peint (0 : non peint, n : extrudeur n), d'après le codage des trancheurs.

    Codage PrusaSlicer, repris par Bambu Studio et OrcaSlicer : chiffres hexadécimaux lus depuis la fin, bits de
    poids faible d'abord. Par nœud : 2 bits de côtés découpés ; 0 = feuille suivie de 2 bits d'état (3 = 3 + 4 bits),
    sinon 2 bits de côté particulier puis les sous-triangles. Chaque sous-triangle compte pour une part égale.
    """
    cached = _PAINT_CACHE.get(code)
    if cached is not None:
        return cached
    try:
        bits = [(int(c, 16) >> k) & 1 for c in reversed(code) for k in range(4)]
    except ValueError:
        return 0
    position, weights = 0, {}

    def read(count: int) -> int:
        nonlocal position
        if position + count > len(bits):
            raise ValueError("truncated paint code")
        value = sum(bits[position + k] << k for k in range(count))
        position += count
        return value

    stack = [1.0]
    try:
        while stack:
            weight = stack.pop()
            split = read(2)
            if split == 0:
                state = read(2)
                if state == 3:
                    state += read(4)
                weights[state] = weights.get(state, 0.0) + weight
            else:
                read(2)
                stack.extend([weight / (split + 1)] * (split + 1))
            if len(weights) > 64 or len(stack) > 4096:
                break
    except ValueError:
        pass
    state = max(weights, key=weights.get) if weights else 0
    if len(_PAINT_CACHE) < 65536:
        _PAINT_CACHE[code] = state
    return state


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


def load_zip(data: bytes) -> DisplayMesh:
    from explorer_preview import scene_formats

    return scene_formats.load_amf(data) if scene_formats.zip_kind(data) == "amf" else load_3mf(data)


def _scene(name):
    def load(data: bytes) -> DisplayMesh:
        from explorer_preview import scene_formats

        return getattr(scene_formats, name)(data)
    return load


LOADERS = {"stl": load_stl, "obj": load_obj, "3mf": load_zip,
           "ply": _scene("load_ply"), "gltf": _scene("load_gltf"), "amf": _scene("load_amf")}
