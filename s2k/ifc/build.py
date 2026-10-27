"""Construcción del modelo desde un IFC: coordenadas locales, secciones, nudos y revisiones.

Pasos:
1. Leer vigas y columnas (extremos del eje y perfil).
2. Estimar la rotación de la grilla con la moda de los ángulos de piezas horizontales (mod 90°).
3. Trasladar y rotar al sistema local; Z = 0 en la cota mínima de la estructura (o la indicada).
4. Crear secciones por designación y barras entre nudos fusionados.
5. Dividir barras en nudos interiores y revisar conectividad.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from ..grid import Grid, SnapStats, detect_grid, snap_point
from ..model import Issue, Model
from ..sections import (
    STEEL_KG_PER_M3,
    angle_section,
    family_of,
    polygon_properties,
    _try_angle,
    SectionSpec,
    check_weight,
    i_section,
    section_from_polygon,
)
from .reader import IfcMember, read_members

DEFAULT_MATERIAL = "A36"


@dataclass
class Transform:
    """Rotación alrededor del origen mundo y luego traslación; Z con desplazamiento."""

    angle_deg: float
    offset: tuple[float, float]
    z0: float

    def apply(self, p) -> tuple[float, float, float]:
        a = math.radians(-self.angle_deg)
        x = p[0] * math.cos(a) - p[1] * math.sin(a) - self.offset[0]
        y = p[0] * math.sin(a) + p[1] * math.cos(a) - self.offset[1]
        return x, y, p[2] - self.z0


@dataclass
class BuildReport:
    source: str
    info: dict
    transform: Transform | None = None
    members: int = 0
    frames: int = 0
    nodes: int = 0
    splits: int = 0
    joined_ends: int = 0
    max_join_move: float = 0.0
    snapped_nodes: int = 0
    duplicates_removed: list[str] = field(default_factory=list)
    grid: Grid | None = None
    grid_stats: SnapStats | None = None
    max_snap_move: float = 0.0
    skipped: list[str] = field(default_factory=list)
    sections: dict[str, SectionSpec] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    candidate_supports: list[int] = field(default_factory=list)
    materials_in_ifc: Counter = field(default_factory=Counter)

    def to_markdown(self) -> str:
        t = self.transform
        out = [f"# Reporte de generación: {self.source}", ""]
        out += ["## Resumen", ""]
        out += [f"- Miembros IFC: {self.members} ({', '.join(f'{k}: {v}' for k, v in self.info['classes'].items())})",
                f"- Origen del eje: {', '.join(f'{k}: {v}' for k, v in self.info['axis_sources'].items())}",
                f"- Extremos llevados al eje de otra barra: {self.joined_ends} "
                f"(desplazamiento máximo {self.max_join_move * 1000:.1f} mm)",
                f"- Nudos ajustados sobre el eje de otra barra: {self.snapped_nodes} "
                f"(desplazamiento máximo {self.max_snap_move * 1000:.1f} mm)",
                f"- Barras en el modelo: {self.frames}",
                f"- Nudos: {self.nodes}",
                f"- Barras divididas en nudos interiores: {self.splits}",
                f"- Escala de unidades IFC: {self.info['length_scale']} m por unidad",
                ""]
        if t:
            out += ["## Transformación a coordenadas locales", "",
                    f"- Rotación de la grilla: {t.angle_deg:.3f}°",
                    f"- Traslación (ejes rotados): x={t.offset[0]:.3f} m, y={t.offset[1]:.3f} m",
                    f"- Cota Z = 0: {t.z0:.3f} m (coordenada mundo)", ""]
        if self.grid is not None:
            out += ["## Grilla regular", ""]
            out += [f"Paso en planta: {self.grid.step_xy} m; paso en Z: {self.grid.step_z} m. "
                    f"Tolerancia de ajuste: {self.grid.tol_xy} m en planta, {self.grid.tol_z} m en Z.", ""]
            out += ["| Eje | Medido (m) | Regular (m) | Diferencia (mm) | Extremos que la respaldan |",
                    "|---|---|---|---|---|"]
            for kind, axes in (("X", self.grid.x), ("Y", self.grid.y), ("Z", self.grid.z)):
                for k, a in enumerate(axes, 1):
                    out.append(f"| {kind}{k} | {a.measured:.3f} | {a.value:.3f} | "
                               f"{(a.value - a.measured) * 1000:+.1f} | {a.support} |")
            out += [""]
            if self.grid_stats is not None:
                out += [f"Coordenadas de extremos ajustadas: {self.grid_stats.coordinates} "
                        f"(desplazamiento máximo {self.grid_stats.max_move * 1000:.1f} mm); "
                        f"fuera de tolerancia: {self.grid_stats.unchanged}", ""]
        out += ["## Secciones", "", "| Sección | Forma SAP | A (m²) | kg/m calc. | kg/m designación | Observaciones |",
                "|---|---|---|---|---|---|"]
        for s in self.sections.values():
            a = f"{s.area:.6f}" if s.area else "SAP calcula"
            w = f"{s.weight_kg_per_m:.2f}" if s.weight_kg_per_m else "—"
            obs = "; ".join(s.warnings) or "ok"
            out.append(f"| {s.name} | {s.shape} | {a} | {w} | {s.kg_per_m or '—'} | {obs} |")
        out += [""]
        out += ["## Materiales encontrados en el IFC", ""]
        out += [f"- {name or '(sin material)'}: {n} miembro(s)" for name, n in self.materials_in_ifc.items()]
        out += ["", f"Todos se asignan a `{DEFAULT_MATERIAL}` (única definición disponible).", ""]
        if self.duplicates_removed:
            out += ["## Barras duplicadas eliminadas", ""]
            out += [f"- GUID {g} (ya existía una barra entre los mismos nudos)" for g in self.duplicates_removed]
            out += [""]
        if self.skipped:
            out += ["## Miembros omitidos", ""] + [f"- {s}" for s in self.skipped] + [""]
        out += ["## Revisiones de conectividad", ""]
        if not self.issues:
            out += ["Sin observaciones."]
        for i in self.issues:
            out += [f"- **{i.severity.upper()}** `{i.code}`: {i.message}"]
        out += ["", "## Apoyos", ""]
        out += [f"Nudos en la cota mínima (candidatos a apoyo, no asignados): {len(self.candidate_supports)}"]
        out += [""]
        return "\n".join(out)


def build(path: str, *, angle_deg: float | None = None, offset: tuple[float, float] | None = None,
          z0: float | None = None, snap_tol: float = 0.01, near_tol: float = 0.10,
          join_radius: float = 0.15, frame_tol: float = 0.02,
          grid_step: float | None = 0.10, z_step: float = 0.05, grid_tol: float = 0.10,
          z_tol: float = 0.10, title: str | None = None) -> tuple[Model, BuildReport]:
    members, info = read_members(path)
    report = BuildReport(source=title or path, info=info, members=len(members))
    report.materials_in_ifc.update(m.material or "" for m in members)

    angle = _grid_angle(members) if angle_deg is None else angle_deg
    rotated = [_rotate(m.p0, angle) for m in members] + [_rotate(m.p1, angle) for m in members]
    if offset is None:
        offset = (min(p[0] for p in rotated), min(p[1] for p in rotated))
    if z0 is None:
        z0 = min(min(m.p0[2], m.p1[2]) for m in members)
    tr = Transform(angle, offset, z0)
    report.transform = tr

    segments = [(tr.apply(m.p0), tr.apply(m.p1)) for m in members]
    if grid_step:
        # La grilla sale de piezas primarias (HN, IN, IE); los arriostramientos no definen ejes.
        points = [p for m, seg in zip(members, segments) if _is_primary(m) for p in seg]
        grid = detect_grid(points, grid_step, z_step, tol_xy=grid_tol, tol_z=z_tol)
        stats = SnapStats()
        # Solo piezas primarias se llevan a la grilla; riostras y cartelas conservan su geometría del IFC.
        segments = [
            (snap_point(a, grid, stats), snap_point(b, grid, stats)) if _is_primary(m) else (a, b)
            for m, (a, b) in zip(members, segments)
        ]
        report.grid = grid
        report.grid_stats = stats

    model = Model(snap_tol=snap_tol, near_tol=near_tol)
    parts_by_key: dict[str, list[tuple[SectionSpec, float]] | None] = {}
    for m, (a, b) in zip(members, segments):
        key = m.designation or m.type_name
        if key not in parts_by_key:
            parts_by_key[key] = _section_parts(m, key, report)
        parts = parts_by_key[key]
        if parts is None:
            report.skipped.append(f"{m.ifc_class} {m.guid} ({m.type_name}): perfil no reconocido")
            continue
        i = model.node(*a)
        j = model.node(*b)
        for spec, angle in parts:
            model.add_section(spec)
            if model.add_frame(i, j, spec.name, m.guid, angle) is None:
                report.skipped.append(f"{m.ifc_class} {m.guid} ({m.type_name}): longitud cero tras fusionar nudos")

    report.splits = model.split_at_nodes()
    report.joined_ends, report.max_join_move = model.attach_free_ends(join_radius)
    report.snapped_nodes, report.max_snap_move = model.snap_nodes_to_frames(frame_tol)
    report.duplicates_removed = model.remove_duplicate_frames()
    report.frames = len(model.frames)
    report.nodes = len(model.nodes)
    report.issues = model.checks()
    report.candidate_supports = model.nodes_at_lowest_level()
    report.sections = {s.name: s for s in model.sections.values()}
    return model, report


def _is_primary(m: IfcMember) -> bool:
    return bool(m.designation) and family_of(m.designation) in ("HN", "IN", "IE")


def _section_parts(m: IfcMember, key: str, report: BuildReport) -> list[tuple[SectionSpec, float]] | None:
    """Secciones y ángulo local de cada barra que representa al miembro.

    Un XL (dos ángulos en cruz) se modela como dos barras de ángulo sobre los mismos nudos, cada una con
    su orientación; así SAP la dibuja como dos L y no como una plancha.
    """
    if m.designation and family_of(m.designation) == "XL" and m.profile is not None \
            and m.profile.kind == "contorno" and len(m.profile.rings) == 2:
        parts = _xl_angles(m)
        if parts is not None:
            return parts
    spec = _section_for(m, key, report)
    return None if spec is None else [(spec, 0.0)]


def _xl_angles(m: IfcMember) -> list[tuple[SectionSpec, float]] | None:
    """Cada contorno de la XL es un ángulo; el segundo gira respecto del primero según su vértice principal."""
    parts: list[tuple[SectionSpec, float]] = []
    specs: dict[str, SectionSpec] = {}  # dos ángulos iguales comparten la misma sección
    ref = _corner_angle(m.profile.rings[0])
    for ring in m.profile.rings:
        dims = _try_angle([ring])
        if dims is None:
            return None
        height, width, t = dims
        name = f"L{height * 1000:.0f}x{width * 1000:.0f}x{t * 1000:.0f}"
        if name not in specs:
            specs[name] = angle_section(name, height, width, t, designation=name)
            specs[name].material = DEFAULT_MATERIAL
        parts.append((specs[name], round((_corner_angle(ring) - ref) % 360, 1)))
    total = sum((s.dims["t3"] + s.dims["t2"] - s.dims["tf"]) * s.dims["tf"] * STEEL_KG_PER_M3 for s, _ in parts)
    if m.kg_per_m and abs(total - m.kg_per_m) / m.kg_per_m > 0.01:
        parts[0][0].warnings.append(f"XL: peso de los dos ángulos {total:.2f} kg/m vs designación {m.kg_per_m} kg/m")
    return parts


def _corner_angle(ring) -> float:
    """Dirección del vértice más alejado del centroide, en grados."""
    pts, _ = ring
    P = polygon_properties([ring])
    far = max(pts, key=lambda p: math.dist(p, (P["cx"], P["cy"])))
    return math.degrees(math.atan2(far[1] - P["cy"], far[0] - P["cx"]))


def _section_for(m: IfcMember, key: str, report: BuildReport) -> SectionSpec | None:
    if m.profile is None:
        return None
    name = key
    if m.profile.kind == "I":
        d = m.profile.dims
        spec = i_section(name, d["d"], d["b"], d["tf"], d["tw"], designation=m.designation)
    else:
        spec = section_from_polygon(name, m.profile.rings, designation=m.designation)
    check_weight(spec, m.kg_per_m)
    spec.material = DEFAULT_MATERIAL
    return spec


def _grid_angle(members: list[IfcMember]) -> float:
    """Ángulo de la grilla: moda de las direcciones de piezas horizontales, en [-45°, 45°)."""
    angles = []
    for m in members:
        dx, dy, dz = (m.p1[k] - m.p0[k] for k in range(3))
        length = math.hypot(dx, dy)
        if length > 1.0 and abs(dz) < 0.01:
            a = math.degrees(math.atan2(dy, dx)) % 90
            angles.append(round(a, 1))
    if not angles:
        return 0.0
    mode = Counter(angles).most_common(1)[0][0]
    return ((mode + 45) % 90) - 45


def _rotate(p, angle_deg: float):
    a = math.radians(-angle_deg)
    return (p[0] * math.cos(a) - p[1] * math.sin(a), p[0] * math.sin(a) + p[1] * math.cos(a), p[2])
