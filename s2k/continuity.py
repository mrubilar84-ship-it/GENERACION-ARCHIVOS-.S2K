"""Continuidad de barras y liberaciones de momento donde la estructura sigue estable.

Reglas (acordadas con el usuario):
- Columnas (verticales) continuas: sin liberaciones.
- Vigas, arriostramientos y demás: M2 y M3 liberados en sus extremos, solo donde el modelo sigue
  siendo estable; torsión liberada únicamente en el extremo I.
- Tramos colineales de la misma sección y ángulo se unen en una barra continua (AUTO MESH en los nudos).
- Apoyos provisorios en la base de las columnas, hasta que el usuario los confirme.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Model
from .stability import M2_IDX, M3_IDX, T_IDX, count_mechanisms

COLLINEAR_COS = 0.9999
VERTICAL_COS = 0.99


@dataclass
class OutFrame:
    label: int
    i: int
    j: int
    section: str
    angle: float
    segments: list[int]
    releases: dict[str, set[int]] = field(default_factory=dict)  # 'i' | 'j' -> índices locales


@dataclass
class Plan:
    frames: list[OutFrame]
    supports: list[int]
    chain_ends: set[int]
    mechanisms_rigid: int
    mechanisms_final: int
    releases_applied: int
    candidates: int
    notes: list[str] = field(default_factory=list)


def _dir(model: Model, label: int) -> tuple[float, float, float]:
    f = model.frames[label]
    a, b = model.nodes[f.i], model.nodes[f.j]
    v = [b[k] - a[k] for k in range(3)]
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _is_vertical(model: Model, label: int) -> bool:
    return abs(_dir(model, label)[2]) >= VERTICAL_COS


def _continues(model: Model, a: int, b: int, n: int) -> bool:
    """¿Los tramos a y b se continúan en el nudo n (colineales, misma sección y ángulo)?"""
    fa, fb = model.frames[a], model.frames[b]
    if fa.section != fb.section or fa.angle != fb.angle:
        return False
    da, db = _dir(model, a), _dir(model, b)
    ua = da if fa.j == n else tuple(-c for c in da)  # dirección con que a llega a n
    ub = db if fb.i == n else tuple(-c for c in db)  # dirección con que b sale de n
    cos = sum(x * y for x, y in zip(ua, ub))
    return cos >= COLLINEAR_COS


def _incident(model: Model) -> dict[int, list[int]]:
    inc: dict[int, list[int]] = {n: [] for n in model.nodes}
    for label, f in model.frames.items():
        inc[f.i].append(label)
        inc[f.j].append(label)
    return inc


def _partner(model: Model, inc: dict[int, list[int]], n: int, label: int) -> int | None:
    """Tramo que continúa a `label` en el nudo n (colineal, misma sección y ángulo); otras barras pueden llegar al nudo."""
    for x in inc[n]:
        if x != label and _continues(model, label, x, n):
            return x
    return None


def build_chains(model: Model) -> list[list[int]]:
    """Agrupa los tramos en barras continuas (listas de etiquetas de tramo, en orden)."""
    inc = _incident(model)
    seen: set[int] = set()
    chains: list[list[int]] = []
    for label in sorted(model.frames):
        if label in seen:
            continue
        chain = [label]
        seen.add(label)
        # hacia ambos lados
        for start_node, direction in ((model.frames[label].i, "front"), (model.frames[label].j, "back")):
            cur, node = label, start_node
            while True:
                nxt = _partner(model, inc, node, cur)
                if nxt is None or nxt in seen:
                    break
                seen.add(nxt)
                if direction == "front":
                    chain.insert(0, nxt)
                else:
                    chain.append(nxt)
                nf = model.frames[nxt]
                node = nf.i if nf.j == node else nf.j
                cur = nxt
        chains.append(chain)
    return chains


def _ends_of_chain(model: Model, chain: list[int]) -> tuple[int, int]:
    """Nudos extremos de la barra continua, en el orden de la cadena."""
    first = model.frames[chain[0]]
    if len(chain) == 1:
        return first.i, first.j
    # orientar el primer tramo: su extremo no compartido con el segundo es el inicio
    second = model.frames[chain[1]]
    start = first.j if first.i in (second.i, second.j) else first.i
    end_frame = model.frames[chain[-1]]
    prev = model.frames[chain[-2]]
    end = end_frame.i if end_frame.j in (prev.i, prev.j) else end_frame.j
    return start, end


def plan(model: Model, releases: bool = True) -> Plan:
    inc = _incident(model)
    chains = build_chains(model)
    notes: list[str] = []

    # extremos de barra continua y candidatos a liberación
    chain_ends: set[int] = set()
    out: list[OutFrame] = []
    candidates: list[tuple[int, str, int]] = []  # (label, 'i'|'j', nodo)
    for chain in chains:
        s, e = _ends_of_chain(model, chain)
        chain_ends |= {s, e}
        f0 = model.frames[chain[0]]
        of = OutFrame(label=0, i=s, j=e, section=f0.section, angle=f0.angle, segments=list(chain))
        out.append(of)
        vertical = _is_vertical(model, chain[0])
        if vertical or not releases:
            continue
        for seg in (chain[0], chain[-1]):
            f = model.frames[seg]
            # solo extremos que son fin de barra continua y que conectan con algo
            for end, node in (("i", f.i), ("j", f.j)):
                if node not in (s, e):
                    continue
                if len(inc[node]) < 2:
                    continue
                candidates.append((seg, end, node))

    # etiquetas de salida
    for k, of in enumerate(out, 1):
        of.label = k
    # mapa tramo -> salida (para liberaciones)
    seg_to_out: dict[int, OutFrame] = {}
    for of in out:
        for seg in of.segments:
            seg_to_out[seg] = of

    # La estabilidad se calcula sobre los tramos del modelo; las liberaciones van solo a extremos de cadena.
    supports = _provisional_supports(model, inc)
    rel_map: dict[tuple[int, str], set[int]] = {}
    mech_rigid = count_mechanisms(model, rel_map, supports)
    notes.append(f"modos de mecanismo con todo rígido: {mech_rigid}")
    applied = 0
    if releases:
        # una liberación se acepta si no agrega mecanismos respecto al modelo rígido
        for seg, end, node in candidates:
            s_key = (seg, end)
            dofs = {M2_IDX, M3_IDX} | ({T_IDX} if end == "i" else set())
            rel_map[s_key] = dofs
            if count_mechanisms(model, rel_map, supports) > mech_rigid:
                del rel_map[s_key]
            else:
                applied += 1
        if mech_rigid > 0:
            notes.append("el modelo rígido tiene mecanismos: las liberaciones solo se aceptan si no agregan más")
    mech_final = count_mechanisms(model, rel_map, supports)

    # traducir liberaciones a barras de salida
    for (seg, end), dofs in rel_map.items():
        of = seg_to_out[seg]
        # el extremo del tramo corresponde a un extremo de la barra de salida solo si es extremo de cadena
        f = model.frames[seg]
        node = f.i if end == "i" else f.j
        if node == of.i:
            of.releases.setdefault("i", set()).update(dofs)
        elif node == of.j:
            of.releases.setdefault("j", set()).update(dofs)
    return Plan(frames=out, supports=sorted(supports), chain_ends=chain_ends,
                mechanisms_rigid=mech_rigid, mechanisms_final=mech_final,
                releases_applied=applied, candidates=len(candidates), notes=notes)


def _provisional_supports(model: Model, inc: dict[int, list[int]]) -> set[int]:
    """Apoyos provisorios: base real de cada columna (nodo inferior que no es tope de otra columna)."""
    vertical = [label for label in model.frames if _is_vertical(model, label)]
    tops = set()
    lows = set()
    for label in vertical:
        f = model.frames[label]
        low, high = (f.i, f.j) if model.nodes[f.i][2] < model.nodes[f.j][2] else (f.j, f.i)
        lows.add(low)
        tops.add(high)
    sup = {n for n in lows if n not in tops}
    if not sup:
        zmin = min(p[2] for p in model.nodes.values())
        sup = {n for n, p in model.nodes.items() if p[2] - zmin <= 0.005}
    return sup
