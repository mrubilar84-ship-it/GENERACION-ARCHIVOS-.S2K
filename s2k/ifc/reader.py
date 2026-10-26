"""Lectura de vigas y columnas desde un IFC (Revit u otro) con ifcopenshell.

Entrega, por miembro, los extremos del eje en coordenadas mundo (metros), su designación
de perfil y el contorno de la sección: como perfil I si el IFC lo define así, o como
contorno cortando el sólido (perfiles plegados, XL, etc.).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from ..sections import parse_designation

Point = tuple[float, float, float]
Rings = list[tuple[list[tuple[float, float]], int]]


@dataclass
class IfcProfile:
    kind: str  # "I" o "contorno"
    ifc_name: str
    dims: dict[str, float] = field(default_factory=dict)  # m, para kind == "I"
    rings: Rings | None = None  # m, para kind == "contorno"


@dataclass
class IfcMember:
    guid: str
    ifc_class: str  # IfcBeam | IfcColumn
    name: str
    type_name: str
    designation: str | None
    kg_per_m: float | None
    p0: Point
    p1: Point
    axis_source: str  # "eje IFC" | "envolvente del sólido (aproximado)"
    profile: IfcProfile | None
    material: str | None


def read_members(path: str) -> tuple[list[IfcMember], dict]:
    """Devuelve (miembros, info). info incluye la escala de unidades y el conteo por clase."""
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.unit as uu

    f = ifcopenshell.open(path)
    length_scale = uu.calculate_unit_scale(f)  # metros por unidad del archivo (0.001 si es mm)
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    members: list[IfcMember] = []
    profile_cache: dict[str, IfcProfile | None] = {}
    for e in f.by_type("IfcBeam") + f.by_type("IfcColumn"):
        ty = ue.get_type(e)
        type_name = ty.Name if ty else (e.ObjectType or e.Name or "")
        shape = ifcopenshell.geom.create_shape(settings, e)
        verts = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
        faces = np.array(shape.geometry.faces, dtype=int).reshape(-1, 3)

        axis = _ifc_axis(e, length_scale)
        if axis is not None:
            p0, p1 = axis
            source = "eje IFC"
        else:
            p0, p1 = _axis_endpoints(verts)
            source = "envolvente del sólido (aproximado)"

        if type_name not in profile_cache:
            profile_cache[type_name] = _profile_of(e, verts, faces, length_scale)
        parsed = parse_designation(type_name)
        mat = ue.get_material(e)
        members.append(IfcMember(
            guid=e.GlobalId, ifc_class=e.is_a(), name=e.Name or "", type_name=type_name,
            designation=parsed[0] if parsed else None, kg_per_m=parsed[1] if parsed else None,
            p0=tuple(float(c) for c in p0), p1=tuple(float(c) for c in p1), axis_source=source,
            profile=profile_cache[type_name], material=mat.Name if mat and hasattr(mat, "Name") else None,
        ))
    info = dict(length_scale=length_scale, ifc_schema=f.schema,
                classes={c: sum(m.ifc_class == c for m in members) for c in ("IfcBeam", "IfcColumn")},
                axis_sources=dict(Counter(m.axis_source for m in members)))
    return members, info


def _ifc_axis(e, length_scale: float):
    """Extremos del eje declarado en la representación 'Axis' (metros, coordenadas mundo).

    Soporta polilíneas y curvas recortadas sobre IfcLine dentro de un IfcMappedItem.
    Devuelve None si el elemento no tiene eje utilizable (p. ej. columnas en este archivo).
    """
    import ifcopenshell.util.placement as up

    axis_rep = [r for r in e.Representation.Representations if r.RepresentationIdentifier == "Axis"]
    if not axis_rep or not axis_rep[0].Items:
        return None
    item = axis_rep[0].Items[0]
    if item.is_a("IfcPolyline"):
        local = [_pad3(p.Coordinates) for p in (item.Points[0], item.Points[-1])]
    elif item.is_a("IfcMappedItem"):
        local = _mapped_trim_points(item)
        if local is None:
            return None
    else:
        return None
    placement = up.get_local_placement(e.ObjectPlacement)
    p0 = (placement @ np.array([*local[0], 1.0]))[:3] * length_scale
    p1 = (placement @ np.array([*local[1], 1.0]))[:3] * length_scale
    return p0, p1


def _mapped_trim_points(item):
    """Extremos de una IfcTrimmedCurve (sobre IfcLine) en un IfcMappedItem, en coordenadas locales de la representación."""
    src = item.MappingSource
    if not src.MappedRepresentation.Items:
        return None
    curve = src.MappedRepresentation.Items[0]
    if not curve.is_a("IfcTrimmedCurve") or not curve.BasisCurve.is_a("IfcLine"):
        return None
    pts = []
    for trim in (curve.Trim1, curve.Trim2):
        cart = [t for t in trim if t.is_a("IfcCartesianPoint")]
        if not cart:
            return None
        pts.append(_pad3(cart[0].Coordinates))
    target = item.MappingTarget
    origin = np.array(_pad3(target.LocalOrigin.Coordinates if target.LocalOrigin else (0, 0, 0)))
    scale = target.Scale or 1.0
    axis1 = _unit(target.Axis1.DirectionRatios if target.Axis1 else (1, 0, 0))
    axis2 = _unit(target.Axis2.DirectionRatios if target.Axis2 else (0, 1, 0))
    axis3 = np.cross(axis1, axis2)
    out = []
    for p in pts:
        q = origin + scale * (axis1 * p[0] + axis2 * p[1] + axis3 * p[2])
        out.append(tuple(q))
    return out


def _pad3(coords) -> tuple[float, float, float]:
    c = list(coords) + [0.0] * (3 - len(coords))
    return float(c[0]), float(c[1]), float(c[2])


def _unit(v) -> np.ndarray:
    a = np.array(list(v) + [0.0] * (3 - len(v)), dtype=float)
    return a / np.linalg.norm(a)


def _axis_endpoints(verts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Extremos del eje principal de la envolvente del sólido (PCA sobre los vértices)."""
    c = verts.mean(axis=0)
    _, _, vt = np.linalg.svd(verts - c, full_matrices=False)
    ax, u, w = vt[0], vt[1], vt[2]
    t = (verts - c) @ ax
    su = (verts - c) @ u
    sw = (verts - c) @ w
    line_point = c + u * (su.min() + su.max()) / 2 + w * (sw.min() + sw.max()) / 2
    return line_point + ax * t.min(), line_point + ax * t.max()


def _profile_of(e, verts: np.ndarray, faces: np.ndarray, length_scale: float) -> IfcProfile | None:
    swept = _swept_area(e)
    if swept is not None and swept.is_a("IfcIShapeProfileDef"):
        return IfcProfile(
            kind="I", ifc_name=swept.ProfileName or "",
            dims=dict(
                d=swept.OverallDepth * length_scale, b=swept.OverallWidth * length_scale,
                tf=swept.FlangeThickness * length_scale, tw=swept.WebThickness * length_scale,
            ),
        )
    rings = _section_by_cut(verts, faces)
    if rings is None:
        return None
    return IfcProfile(kind="contorno", ifc_name=(swept.ProfileName if swept else "") or "", rings=rings)


def _swept_area(e):
    """SweptArea del primer IfcExtrudedAreaSolid, siguiendo IfcMappedItem si hace falta."""
    for rep in e.Representation.Representations:
        for item in rep.Items:
            if item.is_a("IfcMappedItem"):
                for inner in item.MappingSource.MappedRepresentation.Items:
                    if inner.is_a("IfcExtrudedAreaSolid"):
                        return inner.SweptArea
            elif item.is_a("IfcExtrudedAreaSolid"):
                return item.SweptArea
    return None


def _section_by_cut(verts: np.ndarray, faces: np.ndarray) -> Rings | None:
    """Corta el sólido a mitad de luz, perpendicular al eje, y devuelve el contorno (m, plano local).

    El sólido se centra antes del corte para no perder precisión con coordenadas UTM.
    """
    import trimesh
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    c = verts.mean(axis=0)
    local = verts - c
    _, _, vt = np.linalg.svd(local, full_matrices=False)
    ax = vt[0]
    t = local @ ax
    mid = ax * (t.min() + t.max()) / 2
    mesh = trimesh.Trimesh(local, faces, process=True)
    section = mesh.section(plane_origin=mid, plane_normal=ax)
    if section is None:
        return None
    planar, _ = section.to_2D()
    polys = [Polygon(p) for p in planar.discrete if len(p) >= 3]
    if not polys:
        return None
    shape = unary_union(polys).buffer(0)
    geoms = list(shape.geoms) if hasattr(shape, "geoms") else [shape]
    rings: Rings = []
    for g in geoms:
        rings.append(([(float(x), float(y)) for x, y in g.exterior.coords[:-1]], 1))
        rings.extend(([(float(x), float(y)) for x, y in r.coords[:-1]], -1) for r in g.interiors)
    return rings
