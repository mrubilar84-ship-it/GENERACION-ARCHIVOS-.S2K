"""Modelo estructural en memoria: nudos, barras, apoyos y revisiones de conectividad.

Coordenadas en metros. Los nudos que quedan a menos de `snap_tol` se fusionan;
los que quedan entre `snap_tol` y `near_tol` se reportan como posibles desconexiones.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .sections import SectionSpec

Point = tuple[float, float, float]
DOFS = ("U1", "U2", "U3", "R1", "R2", "R3")


@dataclass
class Frame:
    label: int
    i: int
    j: int
    section: str
    source: str = ""  # GlobalId del elemento IFC de origen
    angle: float = 0.0  # rotación del eje local alrededor de la barra, grados


@dataclass
class Issue:
    severity: str  # "error" | "advertencia" | "info"
    code: str
    message: str


@dataclass
class Model:
    snap_tol: float = 0.01
    near_tol: float = 0.10
    cross_tol: float = 0.01
    units: str = "Tonf, m, C"
    nodes: dict[int, Point] = field(default_factory=dict)
    frames: dict[int, Frame] = field(default_factory=dict)
    sections: dict[str, SectionSpec] = field(default_factory=dict)
    restraints: dict[int, tuple[bool, ...]] = field(default_factory=dict)

    # ------------------------------------------------------------ construcción
    def node(self, x: float, y: float, z: float) -> int:
        """Id del nudo en (x, y, z); lo crea si no existe a menos de snap_tol."""
        p = (float(x), float(y), float(z))
        for nid, q in self.nodes.items():
            if math.dist(p, q) <= self.snap_tol:
                return nid
        nid = len(self.nodes) + 1
        self.nodes[nid] = p
        return nid

    def add_section(self, spec: SectionSpec) -> None:
        if spec.name in self.sections and self.sections[spec.name] is not spec:
            raise ValueError(f"Sección duplicada con distinto contenido: {spec.name}")
        self.sections[spec.name] = spec

    def add_frame(self, i: int, j: int, section: str, source: str = "", angle: float = 0.0) -> int | None:
        """Agrega una barra. Devuelve None si es de longitud cero (no se agrega)."""
        if i == j or math.dist(self.nodes[i], self.nodes[j]) <= self.snap_tol:
            return None
        if section not in self.sections:
            raise ValueError(f"Sección no definida: {section}")
        label = max(self.frames, default=0) + 1
        self.frames[label] = Frame(label, i, j, section, source, angle)
        return label

    def restrain(self, node: int, dofs: tuple[bool, ...] = (True,) * 6) -> None:
        if node not in self.nodes:
            raise ValueError(f"Apoyo en nudo inexistente: {node}")
        self.restraints[node] = tuple(dofs)

    def length(self, label: int) -> float:
        f = self.frames[label]
        return math.dist(self.nodes[f.i], self.nodes[f.j])

    # ------------------------------------------------------------ topología
    def split_at_nodes(self) -> int:
        """Divide las barras en cada nudo que cae sobre su interior (p. ej. una viga que pasa por una columna).

        Devuelve el número de divisiones realizadas.
        """
        splits = 0
        changed = True
        while changed:
            changed = False
            for label, f in list(self.frames.items()):
                a, b = self.nodes[f.i], self.nodes[f.j]
                for nid, p in self.nodes.items():
                    if nid in (f.i, f.j):
                        continue
                    if _on_segment(p, a, b, self.snap_tol):
                        del self.frames[label]
                        self.add_frame(f.i, nid, f.section, f.source, f.angle)
                        self.add_frame(nid, f.j, f.section, f.source, f.angle)
                        splits += 1
                        changed = True
                        break
                if changed:
                    break
        self._renumber()
        return splits

    def attach_free_ends(self, radius: float, parallel_deg: float = 10.0, rounds: int = 5) -> tuple[int, float]:
        """Lleva cada extremo libre al eje de otra barra no paralela si queda dentro del alcance de conexión.

        Alcance = `radius` + semialtura de la barra receptora (un arriostramiento puede llegar al ala de una
        columna, no a su eje). Trabaja sobre el grafo ya construido, así el resultado no depende del orden.
        Devuelve (extremos movidos, desplazamiento máximo en m).
        """
        cos_par = math.cos(math.radians(parallel_deg))
        moved, max_move = 0, 0.0
        for _ in range(rounds):
            changed = False
            degree = defaultdict(int)
            for f in self.frames.values():
                degree[f.i] += 1
                degree[f.j] += 1
            for label in list(self.frames):
                f = self.frames[label]
                for end in ("i", "j"):
                    n = getattr(f, end)
                    if degree[n] != 1:
                        continue
                    other = f.j if end == "i" else f.i
                    best = self._best_attachment(label, n, other, cos_par, radius)
                    if best is None:
                        continue
                    q, d = best
                    new = self.node(*q)
                    if new in (n, other):  # evita barras de longitud cero
                        continue
                    f = self.frames[label] = Frame(label, new if end == "i" else f.i,
                                                   new if end == "j" else f.j, f.section, f.source, f.angle)
                    degree[n] -= 1
                    degree[new] += 1
                    moved += 1
                    max_move = max(max_move, d)
                    changed = True
            self.split_at_nodes()
            if not changed:
                break
        return moved, max_move

    def snap_nodes_to_frames(self, tol: float, rounds: int = 3) -> tuple[int, float]:
        """Mueve cada nudo que quede a menos de `tol` del interior de una barra no incidente sobre ese eje.

        Corrige uniones con desfase de centímetros (nudo de riostra a 1 cm del eje de una viga). Luego fusiona
        nudos coincidentes y divide las barras. Devuelve (nudos movidos, desplazamiento máximo en m).
        """
        moved, max_move = 0, 0.0
        for _ in range(rounds):
            changed = False
            for n in list(self.nodes):
                P = self.nodes[n]
                best = None
                for g in self.frames.values():
                    if n in (g.i, g.j):
                        continue
                    A, B = self.nodes[g.i], self.nodes[g.j]
                    q, d = _closest_on_segment(P, A, B)
                    interior = min(math.dist(q, A), math.dist(q, B)) > self.snap_tol
                    if interior and d <= tol and d > 1e-9 and (best is None or d < best[1]):
                        best = (q, d)
                if best:
                    self.nodes[n] = tuple(best[0])
                    moved += 1
                    max_move = max(max_move, best[1])
                    changed = True
            self._merge_coincident()
            self.split_at_nodes()
            if not changed:
                break
        return moved, max_move

    def remove_duplicate_frames(self) -> list[str]:
        """Elimina barras repetidas entre los mismos dos nudos (duplicarían peso y rigidez en SAP).

        Conserva la primera. Devuelve los GUID de origen de las barras eliminadas.
        """
        seen: dict[tuple, int] = {}
        removed: list[str] = []
        for label in sorted(self.frames):
            f = self.frames[label]
            key = (min(f.i, f.j), max(f.i, f.j), f.section, f.angle)
            if key in seen:
                removed.append(f.source)
                del self.frames[label]
            else:
                seen[key] = label
        if removed:
            self._renumber()
        return removed

    def _merge_coincident(self) -> None:
        """Une nudos a menos de snap_tol: reasigna las barras al de menor id."""
        keep: dict[int, int] = {}
        ids = sorted(self.nodes)
        for n in ids:
            if n in keep:
                continue
            for m in ids:
                if m > n and m not in keep and math.dist(self.nodes[n], self.nodes[m]) <= self.snap_tol:
                    keep[m] = n
        if not keep:
            return
        for label, f in list(self.frames.items()):
            self.frames[label] = Frame(label, keep.get(f.i, f.i), keep.get(f.j, f.j), f.section, f.source, f.angle)
        for m in keep:
            self.restraints.pop(m, None)
        self._prune_nodes()

    def _best_attachment(self, label: int, n: int, other: int, cos_par: float, radius: float):
        f = self.frames[label]
        P = self.nodes[n]
        u = _direction(self.nodes[f.i], self.nodes[f.j])
        best = None
        for g in self.frames.values():
            if g.label == label or n in (g.i, g.j):
                continue
            v = _direction(self.nodes[g.i], self.nodes[g.j])
            parallel = abs(sum(u[k] * v[k] for k in range(3))) >= cos_par
            q, d = _closest_on_segment(P, self.nodes[g.i], self.nodes[g.j])
            at_end = min(math.dist(q, self.nodes[g.i]), math.dist(q, self.nodes[g.j])) < 1e-9
            if parallel and not at_end:  # paralelas solo se conectan extremo con extremo (continuación en línea)
                continue
            if math.dist(q, self.nodes[other]) <= self.snap_tol:  # el destino sería el otro extremo de la misma barra
                continue
            if d > self.snap_tol and d <= radius + self.reach(g.section) and (best is None or d < best[1]):
                best = (q, d)
        return best

    def reach(self, section: str) -> float:
        """Semialtura de la sección: distancia máxima desde el eje hasta la cara de la pieza."""
        spec = self.sections[section]
        if "t3" in spec.dims:
            return spec.dims["t3"] / 2
        return math.sqrt(spec.area or 0.0) / 2

    def _prune_nodes(self) -> None:
        used = {n for f in self.frames.values() for n in (f.i, f.j)}
        used |= set(self.restraints)
        self.nodes = {n: p for n, p in self.nodes.items() if n in used}

    def _renumber(self) -> None:
        ordered = sorted(self.frames.values(), key=lambda f: f.label)
        self.frames = {k + 1: Frame(k + 1, f.i, f.j, f.section, f.source, f.angle) for k, f in enumerate(ordered)}
        self._prune_nodes()

    def components(self) -> list[set[int]]:
        adj: dict[int, set[int]] = defaultdict(set)
        for f in self.frames.values():
            adj[f.i].add(f.j)
            adj[f.j].add(f.i)
        seen: set[int] = set()
        comps: list[set[int]] = []
        for start in self.nodes:
            if start in seen:
                continue
            comp, stack = set(), [start]
            while stack:
                n = stack.pop()
                if n in comp:
                    continue
                comp.add(n)
                stack.extend(adj[n] - comp)
            seen |= comp
            comps.append(comp)
        return comps

    def nodes_at_lowest_level(self, tol: float = 0.005) -> list[int]:
        """Nudos en la cota mínima: candidatos a apoyo. No se asignan automáticamente."""
        zmin = min(p[2] for p in self.nodes.values())
        return sorted(n for n, p in self.nodes.items() if p[2] - zmin <= tol)

    # ------------------------------------------------------------ revisiones
    def checks(self) -> list[Issue]:
        issues: list[Issue] = []
        used = {n for f in self.frames.values() for n in (f.i, f.j)}
        orphans = sorted(set(self.nodes) - used)
        if orphans:
            issues.append(Issue("error", "NUDO_DESCONECTADO",
                                f"{len(orphans)} nudo(s) sin barras: {_fmt_nodes(self, orphans)}"))

        comps = self.components()
        if len(comps) > 1:
            sizes = sorted((len(c) for c in comps), reverse=True)
            issues.append(Issue("error", "COMPONENTES_SEPARADOS",
                                f"{len(comps)} componentes conectadas (tamaños de nudos {sizes}); "
                                "revisar si la estructura realmente está separada o faltan elementos"))

        keys = [(tuple(sorted((f.i, f.j))), f.section, f.angle) for f in self.frames.values()]
        dups = len(keys) - len(set(keys))
        if dups:
            issues.append(Issue("error", "BARRA_DUPLICADA", f"{dups} barra(s) duplicada(s)"))

        for label, f in self.frames.items():
            if self.length(label) <= self.snap_tol:
                issues.append(Issue("error", "BARRA_LONGITUD_CERO", f"barra {label} de longitud cero"))

        for n in self.restraints:
            if n not in self.nodes:
                issues.append(Issue("error", "APOYO_INVALIDO", f"apoyo en nudo {n} inexistente"))

        issues.extend(self._near_misses())
        issues.extend(self._crossings())
        return issues

    def _near_misses(self) -> list[Issue]:
        out = []
        ids = sorted(self.nodes)
        for a_idx, a in enumerate(ids):
            for b in ids[a_idx + 1:]:
                d = math.dist(self.nodes[a], self.nodes[b])
                if self.snap_tol < d <= self.near_tol:
                    out.append(Issue("advertencia", "NUDOS_CERCANOS",
                                     f"nudos {a} y {b} separados {d * 1000:.1f} mm (no fusionados); "
                                     "posible desconexión"))
        return out

    def _crossings(self) -> list[Issue]:
        """Barras que se cruzan o rozan en su interior sin compartir nudo."""
        out = []
        labels = sorted(self.frames)
        for k, la in enumerate(labels):
            fa = self.frames[la]
            for lb in labels[k + 1:]:
                fb = self.frames[lb]
                if {fa.i, fa.j} & {fb.i, fb.j}:
                    continue
                if _segments_touch(self.nodes[fa.i], self.nodes[fa.j], self.nodes[fb.i], self.nodes[fb.j], self.cross_tol):
                    out.append(Issue("advertencia", "BARRAS_SIN_NUDO",
                                     f"barras {la} y {lb} se cruzan o rozan sin nudo común"))
        return out


# ------------------------------------------------------------ geometría auxiliar

def _direction(a, b) -> list[float]:
    v = [b[k] - a[k] for k in range(3)]
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def _closest_on_segment(p, a, b) -> tuple[list[float], float]:
    ab = [b[k] - a[k] for k in range(3)]
    L2 = sum(c * c for c in ab)
    t = 0.0 if L2 == 0 else min(max(sum((p[k] - a[k]) * ab[k] for k in range(3)) / L2, 0.0), 1.0)
    q = [a[k] + t * ab[k] for k in range(3)]
    return q, math.dist(p, q)


def _on_segment(p, a, b, tol) -> bool:
    ab = [b[k] - a[k] for k in range(3)]
    L2 = sum(c * c for c in ab)
    if L2 == 0:
        return False
    t = sum((p[k] - a[k]) * ab[k] for k in range(3)) / L2
    if not (0 < t < 1):
        return False
    closest = [a[k] + t * ab[k] for k in range(3)]
    return math.dist(p, closest) <= tol


def _segments_touch(p1, p2, q1, q2, tol) -> bool:
    """Distancia mínima entre dos segmentos 3D menor que tol."""
    return _segment_distance(p1, p2, q1, q2) <= tol


def _segment_distance(p1, p2, q1, q2) -> float:
    """Distancia mínima entre dos segmentos 3D. Robusta a segmentos de longitud cero."""
    u = [p2[k] - p1[k] for k in range(3)]
    v = [q2[k] - q1[k] for k in range(3)]
    a = sum(c * c for c in u)
    c = sum(c * c for c in v)
    if a == 0 and c == 0:
        return math.dist(p1, q1)
    if a == 0:
        return _closest_on_segment(p1, q1, q2)[1]
    if c == 0:
        return _closest_on_segment(q1, p1, p2)[1]
    w = [p1[k] - q1[k] for k in range(3)]
    b = sum(u[k] * v[k] for k in range(3))
    d = sum(u[k] * w[k] for k in range(3))
    e = sum(v[k] * w[k] for k in range(3))
    D = a * c - b * b
    s = min(max((b * e - c * d) / D, 0.0), 1.0) if D > 1e-12 else 0.0
    t = (b * s + e) / c
    if t < 0:
        t, s = 0.0, min(max(-d / a, 0.0), 1.0)
    elif t > 1:
        t, s = 1.0, min(max((b - d) / a, 0.0), 1.0)
    pa = [p1[k] + s * u[k] for k in range(3)]
    pb = [q1[k] + t * v[k] for k in range(3)]
    return math.dist(pa, pb)


def _fmt_nodes(model: Model, ids, limit: int = 10) -> str:
    parts = [f"{n} {tuple(round(c, 3) for c in model.nodes[n])}" for n in ids[:limit]]
    more = f" (+{len(ids) - limit} más)" if len(ids) > limit else ""
    return "; ".join(parts) + more
