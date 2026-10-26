"""Escritura de un Model al formato de texto .s2k de SAP2000.

El formato es una secuencia de bloques "TABLE:" seguidos de líneas
"Campo=valor". Los nombres de tabla y de campos siguen la convención
que usa SAP2000 al exportar; conviene validar cualquier cambio abriendo
el archivo generado en SAP2000.
"""

from pathlib import Path

from .model import Model

DOF_NAMES = ("U1", "U2", "U3", "R1", "R2", "R3")


def _quote(value: str) -> str:
    return f'"{value}"' if " " in value or "/" in value else value


def _yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"


def _table(name: str, rows: list[str]) -> list[str]:
    lines = [f'TABLE:  "{name}"']
    lines.extend(f"   {row}" for row in rows)
    lines.append("")
    return lines


def _materials(model: Model) -> list[str]:
    rows = [
        f"Material={_quote(m.name)} Type=Steel SymType=Isotropic TempDepend=No Color=Yellow"
        for m in model.materials.values()
    ]
    return _table("MATERIAL PROPERTIES 01 - GENERAL", rows)


def _material_mechanics(model: Model) -> list[str]:
    rows = [
        f"Material={_quote(m.name)} UnitWeight={m.unit_weight} "
        f"UnitMass={m.unit_weight / 9.80665} E1={m.e1} G12={m.e1 / (2 * (1 + m.u12))} U12={m.u12}"
        for m in model.materials.values()
    ]
    return _table("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES", rows)


def _frame_sections(model: Model) -> list[str]:
    rows = [
        f"SectionName={_quote(s.name)} Material={_quote(s.material)} "
        f"Shape={_quote(s.shape)} t3={s.t3} t2={s.t2}"
        for s in model.sections.values()
    ]
    return _table("FRAME SECTION PROPERTIES 01 - GENERAL", rows)


def _joint_coordinates(model: Model) -> list[str]:
    rows = [
        f"Joint={j.label} CoordSys=GLOBAL CoordType=Cartesian "
        f"XorR={j.x} Y={j.y} Z={j.z} SpecialJt=No "
        f"GlobalX={j.x} GlobalY={j.y} GlobalZ={j.z}"
        for j in model.joints.values()
    ]
    return _table("JOINT COORDINATES", rows)


def _connectivity(model: Model) -> list[str]:
    rows = [
        f"Frame={f.label} JointI={f.joint_i} JointJ={f.joint_j} "
        f"IsCurved=No Length={model.frame_length(f):.6g}"
        for f in model.frames
    ]
    return _table("CONNECTIVITY - FRAME", rows)


def _frame_assignments(model: Model) -> list[str]:
    rows = [
        f"Frame={f.label} AnalSect={_quote(f.section)} "
        f"DesignSect={_quote(f.section)} MatProp=Default"
        for f in model.frames
    ]
    return _table("FRAME SECTION ASSIGNMENTS", rows)


def _restraints(model: Model) -> list[str]:
    rows = []
    for r in model.restraints:
        flags = " ".join(f"{name}={_yes_no(v)}" for name, v in zip(DOF_NAMES, r.fixed))
        rows.append(f"Joint={r.joint} {flags}")
    return _table("JOINT RESTRAINT ASSIGNMENTS", rows)


def render(model: Model) -> str:
    """Devuelve el contenido .s2k completo del modelo."""
    lines: list[str] = []
    for block in (
        _materials,
        _material_mechanics,
        _frame_sections,
        _joint_coordinates,
        _connectivity,
        _frame_assignments,
        _restraints,
    ):
        lines.extend(block(model))
    return "\n".join(lines) + "\n"


def write(model: Model, path: str | Path) -> Path:
    """Escribe el modelo en un archivo .s2k y devuelve la ruta."""
    path = Path(path)
    path.write_text(render(model), encoding="utf-8")
    return path
