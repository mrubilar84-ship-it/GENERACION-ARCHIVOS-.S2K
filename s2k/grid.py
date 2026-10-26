"""Grilla regular a partir de las coordenadas medidas de la estructura.

Pasos:
1. Agrupa las coordenadas de los extremos de barras en líneas (X, Y) y niveles (Z).
   Un grupo es línea si tiene al menos `min_support` extremos.
2. Regulariza: cada espaciamiento medido se redondea al paso (p. ej. 5,05 → 5,10 con paso 0,10).
   La primera línea también se lleva al paso, así la grilla queda en valores cerrados.
3. Ajusta cada coordenada de extremo a la línea regular más cercana, si queda dentro de la tolerancia.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Axis:
    label: str
    measured: float  # centro del grupo de coordenadas medidas (m)
    value: float  # posición regular (m)
    support: int  # extremos que la respaldan


@dataclass
class Grid:
    x: list[Axis] = field(default_factory=list)
    y: list[Axis] = field(default_factory=list)
    z: list[Axis] = field(default_factory=list)
    step_xy: float = 0.10
    step_z: float = 0.05
    tol_xy: float = 0.15
    tol_z: float = 0.10


@dataclass
class SnapStats:
    coordinates: int = 0  # coordenadas ajustadas
    unchanged: int = 0  # coordenadas que no quedaron cerca de una línea
    max_move: float = 0.0


def detect_grid(points, step_xy: float, step_z: float, tol_xy: float = 0.15, tol_z: float = 0.10,
                cluster_tol: float = 0.10, min_support: int = 4) -> Grid:
    """Detecta líneas X, Y y niveles Z a partir de los extremos (lista de (x, y, z), en metros)."""
    grid = Grid(step_xy=step_xy, step_z=step_z, tol_xy=tol_xy, tol_z=tol_z)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    grid.x = _axes(xs, step_xy, cluster_tol, min_support, prefix="")
    grid.y = _axes(ys, step_xy, cluster_tol, min_support, prefix="")
    grid.z = _axes(zs, step_z, cluster_tol, min_support, prefix="N")
    return grid


def snap_point(p, grid: Grid, stats: SnapStats | None = None) -> tuple[float, float, float]:
    """Lleva cada coordenada a su línea regular si está dentro de la tolerancia."""
    out = [
        _snap_value(p[0], grid.x, grid.tol_xy, stats),
        _snap_value(p[1], grid.y, grid.tol_xy, stats),
        _snap_value(p[2], grid.z, grid.tol_z, stats),
    ]
    return out[0], out[1], out[2]


def _axes(values, step: float, cluster_tol: float, min_support: int, prefix: str) -> list[Axis]:
    groups = _cluster(values, cluster_tol, min_support)
    if not groups:
        return []
    axes: list[Axis] = []
    value = _round_to(groups[0][0], step)
    for k, (center, support) in enumerate(groups):
        if k > 0:
            spacing = groups[k][0] - groups[k - 1][0]
            value += max(1, _nearest_count(spacing, step)) * step
        axes.append(Axis(label=f"{prefix}{k + 1}", measured=center, value=round(value, 6), support=support))
    return axes


def _cluster(values, tol: float, min_support: int) -> list[tuple[float, int]]:
    vals = sorted(values)
    if not vals:
        return []
    groups: list[list[float]] = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [(sum(g) / len(g), len(g)) for g in groups if len(g) >= min_support]


def _round_to(v: float, step: float) -> float:
    return round(_nearest_count(v, step) * step, 6)


def _nearest_count(v: float, step: float) -> int:
    """Número de pasos más cercano; el medio se redondea hacia arriba (5,05 con paso 0,10 → 51)."""
    return math.floor(v / step + 0.5 + 1e-9)


def _snap_value(v: float, axes: list[Axis], tol: float, stats: SnapStats | None) -> float:
    if not axes:
        return v
    best = min(axes, key=lambda a: abs(a.measured - v))
    d = abs(best.measured - v)
    if d > tol:
        if stats is not None:
            stats.unchanged += 1
        return v
    if stats is not None:
        stats.coordinates += 1 if abs(best.value - v) > 1e-9 else 0
        stats.max_move = max(stats.max_move, abs(best.value - v))
    return best.value
