"""Secciones de frame: designación chilena, propiedades geométricas y forma SAP2000.

Unidades internas: metros y metros cuadrados. Las dimensiones que llegan desde
un IFC (mm) se convierten antes de llegar aquí.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

STEEL_KG_PER_M3 = 7850.0
WEIGHT_TOLERANCE = 0.01  # 1 % entre peso calculado y designación

_DESIGNATION = re.compile(r"(?P<family>\d?[A-Z]+)(?P<h>\d+(?:\.\d+)?)x(?P<kg>\d+(?:\.\d+)?)$")


@dataclass
class SectionSpec:
    """Sección lista para escribir como FRAME SECTION PROPERTIES 01."""

    name: str
    shape: str  # texto SAP: "I/Wide Flange", "Angle", "General"
    dims: dict[str, float]
    props: dict[str, float] | None  # None: SAP calcula las propiedades a partir de las dimensiones
    material: str = "A36"
    designation: str | None = None
    kg_per_m: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def area(self) -> float | None:
        return self.props["A"] if self.props else None

    @property
    def weight_kg_per_m(self) -> float | None:
        return self.area * STEEL_KG_PER_M3 if self.area else None


def parse_designation(text: str) -> tuple[str, float] | None:
    """'Viga HN Soldado:HN30x92.2' -> ('HN30x92.2', 92.2). Devuelve None si no hay designación."""
    m = _DESIGNATION.search(text.strip())
    if not m:
        return None
    return m.group(0), float(m.group("kg"))


def family_of(designation: str) -> str:
    return _DESIGNATION.search(designation).group("family")


# ------------------------------------------------------------------ propiedades

def props_i_shape(d: float, b: float, tf: float, tw: float) -> dict[str, float]:
    """Perfil I/H doblemente simétrico, sin filetes. d: altura, b: ancho de ala."""
    hw = d - 2 * tf
    A = 2 * b * tf + hw * tw
    I33 = (b * d**3 - (b - tw) * hw**3) / 12
    I22 = (2 * tf * b**3 + hw * tw**3) / 12
    J = (2 * b * tf**3 + hw * tw**3) / 3
    return dict(
        A=A, J=J, I33=I33, I22=I22, I23=0.0,
        AS2=d * tw, AS3=5 / 6 * 2 * b * tf,
        S33=I33 / (d / 2), S22=I22 / (b / 2),
        Z33=b * tf * (d - tf) + tw * hw**2 / 4, Z22=tf * b**2 / 2 + hw * tw**2 / 4,
    )


def polygon_properties(rings: list[tuple[list[tuple[float, float]], int]]) -> dict[str, float]:
    """Propiedades de una sección poligonal arbitraria (metros).

    rings: lista de (puntos, signo); signo +1 sólido, -1 hueco.
    Devuelve área, centroide, inercias respecto al centroide e inercias principales.
    """
    A = Sx = Sy = 0.0
    for pts, sign in rings:
        a, sx, sy = _ring_first_moments(pts)
        A += sign * abs(a)
        Sx += sign * sx * math.copysign(1, a)
        Sy += sign * sy * math.copysign(1, a)
    cx, cy = Sy / A, Sx / A
    Ixx = Iyy = Ixy = 0.0
    for pts, sign in rings:
        centred = [(x - cx, y - cy) for x, y in pts]
        a, ixx, iyy, ixy = _ring_second_moments(centred)
        s = sign * math.copysign(1, a)
        Ixx += s * ixx
        Iyy += s * iyy
        Ixy += s * ixy
    avg = (Ixx + Iyy) / 2
    r = math.hypot((Ixx - Iyy) / 2, Ixy)
    return dict(A=A, cx=cx, cy=cy, Ixx=Ixx, Iyy=Iyy, Ixy=Ixy, I1=avg + r, I2=avg - r)


def _ring_first_moments(p):
    a = sx = sy = 0.0
    for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1]):
        c = x0 * y1 - x1 * y0
        a += c
        sx += (y0 + y1) * c
        sy += (x0 + x1) * c
    return a / 2, sx / 6, sy / 6


def _ring_second_moments(p):
    a = ixx = iyy = ixy = 0.0
    for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1]):
        c = x0 * y1 - x1 * y0
        a += c
        ixx += c * (y0 * y0 + y0 * y1 + y1 * y1)
        iyy += c * (x0 * x0 + x0 * x1 + x1 * x1)
        ixy += c * (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0)
    return a / 2, ixx / 12, iyy / 12, ixy / 24


def _perimeter(rings) -> float:
    return sum(math.dist(p, q) for pts, _ in rings for p, q in zip(pts, pts[1:] + pts[:1]))


# ------------------------------------------------------------------ constructores

def i_section(name: str, d: float, b: float, tf: float, tw: float, designation: str | None = None) -> SectionSpec:
    """Perfil I desde dimensiones (metros)."""
    dims = dict(t3=d, t2=b, tf=tf, tw=tw, t2b=b, tfb=tf, FilletRadius=0.0)
    return SectionSpec(name, "I/Wide Flange", dims, props_i_shape(d, b, tf, tw), designation=designation)


def angle_section(name: str, height: float, width: float, t: float, designation: str | None = None) -> SectionSpec:
    """Ángulo L: SAP calcula sus propiedades a partir de las dimensiones."""
    dims = dict(t3=height, t2=width, tf=t, tw=t, FilletRadius=0.0)
    return SectionSpec(name, "Angle", dims, None, designation=designation)


def general_section(name: str, rings, designation: str | None = None) -> SectionSpec:
    """Sección general desde un contorno (metros). Ejes: principales, sin rotación respecto a los locales."""
    P = polygon_properties(rings)
    A = P["A"]
    per = _perimeter(rings)
    t_eq = 2 * A / per  # espesor equivalente de pared delgada para la torsión (aproximación)
    pts = _flat(rings)
    c_max = max(max(math.dist(p, (P["cx"], P["cy"])) for p in pts), 1e-9)
    props = dict(
        A=A, J=per * t_eq**3 / 3, I33=P["I1"], I22=P["I2"], I23=0.0,
        AS2=5 / 6 * A, AS3=5 / 6 * A,
        S33=P["I1"] / c_max, S22=P["I2"] / c_max,
        Z33=P["I1"] / c_max, Z22=P["I2"] / c_max,
    )
    spec = SectionSpec(name, "General", {}, props, designation=designation)
    spec.warnings.append("sección general: torsión aproximada y ejes principales; validar en SAP2000")
    return spec


def _flat(rings):
    return [pt for pts, _ in rings for pt in pts]


def section_from_polygon(name: str, rings, designation: str | None = None) -> SectionSpec:
    """Clasifica un contorno: ángulo L y perfil I (familias HN, IN, IE) por geometría; el resto va como General."""
    family = family_of(designation) if designation else ""
    if family == "L":
        angle = _try_angle(rings)
        if angle is not None:
            height, width, t = angle
            return angle_section(name, height, width, t, designation)
    if family in ("HN", "IN", "IE"):
        fit = _try_i_shape(rings)
        if fit is not None:
            d, b, tf, tw = fit
            return i_section(name, d, b, tf, tw, designation)
    return general_section(name, rings, designation)


def _try_i_shape(rings, tol: float = 0.03):
    """Ajusta espesores de ala y alma de un perfil I a un contorno: A y la inercia fuerte deben coincidir (±tol).

    Depth d = dimensión mayor de la caja envolvente; el eje fuerte es el de mayor inercia principal.
    """
    pts = _flat(rings)
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    W, H = max(xs) - min(xs), max(ys) - min(ys)
    d, b = max(W, H), min(W, H)
    P = polygon_properties(rings)
    A, I_strong = P["A"], P["I1"]
    best = None
    steps = 400
    for k in range(1, steps):
        tf = (k / steps) * b / 2
        tw = (A - 2 * b * tf) / (d - 2 * tf) if d - 2 * tf > 0 else -1
        if tw <= 0 or tw >= b:
            continue
        I_fit = (b * d**3 - (b - tw) * (d - 2 * tf) ** 3) / 12
        err = abs(I_fit - I_strong) / I_strong
        if best is None or err < best[0]:
            best = (err, tf, tw)
    if best is None or best[0] > tol:
        return None
    _, tf, tw = best
    if abs((2 * b * tf + (d - 2 * tf) * tw) - A) / A > tol:
        return None
    return d, b, tf, tw


def _try_angle(rings):
    """Ángulo de lados rectos: area = (W + H - t) * t, con W, H las dimensiones de la caja envolvente."""
    pts = _flat(rings)
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    W, H = max(xs) - min(xs), max(ys) - min(ys)
    A = polygon_properties(rings)["A"]
    disc = (W + H) ** 2 - 4 * A
    if disc < 0:
        return None
    t = ((W + H) - math.sqrt(disc)) / 2
    if abs((W + H - t) * t - A) / A > 0.02:
        return None
    return max(W, H), min(W, H), t


def check_weight(spec: SectionSpec, designation_kg_per_m: float | None) -> None:
    """Compara el peso calculado con el de la designación (±1 %)."""
    spec.kg_per_m = designation_kg_per_m
    w = spec.weight_kg_per_m
    if w is None or not designation_kg_per_m:
        return
    err = (w - designation_kg_per_m) / designation_kg_per_m
    if abs(err) > WEIGHT_TOLERANCE:
        spec.warnings.append(
            f"peso calculado {w:.2f} kg/m vs designación {designation_kg_per_m} kg/m ({err:+.1%})"
        )
