"""Escritura del modelo a texto .s2k de SAP2000.

Formato verificado contra archivos exportados por SAP2000 v23.3.1 (ver tablas del kit de referencia):
- CRLF como fin de línea, sangría de 3 espacios en cada registro, pares clave=valor separados por 3 espacios.
- Valores con espacios, comas, '/' o '=' van entre comillas.
- Cada tabla termina con una línea de un espacio; el archivo termina con END TABLE DATA.
"""

from __future__ import annotations

import math
from pathlib import Path

from .model import DOFS, Model

# A36 en Tonf, m, C (valores exactos que exporta SAP2000)
A36 = dict(
    UnitWeight=7.84904757236607, UnitMass=0.80038007068661,
    E1=20389019.1580383, G12=7841930.44539935, U12=0.3, A1=1.16999994421006e-05,
    Fy=25310.5065410131, Fu=40778.0383160766, EffFy=37965.7598115196, EffFu=44855.8421476843,
)
MATERIALS = {"A36": A36}


def _q(value) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.10g}".replace("e", "E")
    s = str(value)
    if s == "" or any(c in s for c in ' ,"=():/'):
        return '"' + s.replace('"', "'") + '"'
    return s


def _rec(**kw) -> str:
    return "   " + "   ".join(f"{k}={_q(v)}" for k, v in kw.items())


def _table(name: str, rows: list[str]) -> list[str]:
    if not rows:
        return []
    return [f'TABLE:  "{name}"', *rows, " "]


def render(model: Model, title: str = "generado desde IFC con s2k") -> str:
    """Contenido .s2k del modelo (CRLF)."""
    lines: list[str] = [f"File {title}", " "]
    used_materials = sorted({s.material for s in model.sections.values()} or {"A36"})
    for m in used_materials:
        if m not in MATERIALS:
            raise ValueError(f"Material sin propiedades definidas: {m}")

    lines += _table("PROGRAM CONTROL", [_rec(
        ProgramName="SAP2000", Version="23.3.1", ProgLevel="Advanced", CurrUnits=model.units,
        SteelCode="AISC 360-16", ConcCode="ACI 318-19", AlumCode="AA 2015", ColdCode="AISI-16", RegenHinge=True,
    )])
    lines += _table("ACTIVE DEGREES OF FREEDOM", [_rec(UX=True, UY=True, UZ=True, RX=True, RY=True, RZ=True)])
    lines += _table("MATERIAL PROPERTIES 01 - GENERAL", [
        _rec(Material=m, Type="Steel", Grade="Grade 36", SymType="Isotropic", TempDepend=False, Color="Blue")
        for m in used_materials])
    lines += _table("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES", [
        _rec(Material=m, UnitWeight=A36["UnitWeight"], UnitMass=A36["UnitMass"], E1=A36["E1"],
             G12=A36["G12"], U12=A36["U12"], A1=A36["A1"])
        for m in used_materials])
    lines += _table("MATERIAL PROPERTIES 03A - STEEL DATA", [
        _rec(Material=m, Fy=A36["Fy"], Fu=A36["Fu"], EffFy=A36["EffFy"], EffFu=A36["EffFu"], SSCurveOpt="Simple",
             SSHysType="Kinematic", SHard=0.02, SMax=0.14, SRup=0.2, FinalSlope=-0.1, CoupModType="Von Mises")
        for m in used_materials])

    section_rows = []
    for s in model.sections.values():
        kw = dict(SectionName=s.name, Material=s.material, Shape=s.shape)
        kw.update(s.dims)
        if s.props:
            p = s.props
            kw.update(Area=p["A"], TorsConst=p["J"], I33=p["I33"], I22=p["I22"], I23=p.get("I23", 0.0),
                      AS2=p["AS2"], AS3=p["AS3"], S33=p["S33"], S22=p["S22"], Z33=p["Z33"], Z22=p["Z22"],
                      R33=math.sqrt(p["I33"] / p["A"]), R22=math.sqrt(p["I22"] / p["A"]))
        kw.update(ConcCol=False, ConcBeam=False, Color="Blue", FromFile=False,
                  AMod=1, A2Mod=1, A3Mod=1, JMod=1, I2Mod=1, I3Mod=1, MMod=1, WMod=1)
        if s.designation:
            kw["Notes"] = s.designation
        section_rows.append(_rec(**kw))
    lines += _table("FRAME SECTION PROPERTIES 01 - GENERAL", section_rows)

    lines += _table("JOINT COORDINATES", [
        _rec(Joint=n, CoordSys="GLOBAL", CoordType="Cartesian", XorR=x, Y=y, Z=z, SpecialJt=False,
             GlobalX=x, GlobalY=y, GlobalZ=z)
        for n, (x, y, z) in model.nodes.items()])

    conn, assign = [], []
    for label, f in model.frames.items():
        a, b = model.nodes[f.i], model.nodes[f.j]
        conn.append(_rec(Frame=label, JointI=f.i, JointJ=f.j, IsCurved=False, Length=math.dist(a, b),
                         CentroidX=(a[0] + b[0]) / 2, CentroidY=(a[1] + b[1]) / 2, CentroidZ=(a[2] + b[2]) / 2))
        shape = model.sections[f.section].shape
        assign.append(_rec(Frame=label, SectionType=shape, AutoSelect="N.A.", AnalSect=f.section,
                           DesignSect=f.section, MatProp="Default"))
    lines += _table("CONNECTIVITY - FRAME", conn)
    lines += _table("FRAME SECTION ASSIGNMENTS", assign)
    lines += _table("FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL", [
        _rec(Frame=label, Angle=f.angle, AdvanceAxes=False)
        for label, f in model.frames.items() if f.angle])

    lines += _table("JOINT RESTRAINT ASSIGNMENTS", [
        _rec(Joint=n, **{d: bool(v) for d, v in zip(DOFS, dofs)}) for n, dofs in model.restraints.items()])

    lines.append("END TABLE DATA")
    return "\r\n".join(lines) + "\r\n"


def write(model: Model, path: str | Path, title: str | None = None) -> Path:
    path = Path(path)
    text = render(model, title or path.name)
    path.write_bytes(text.encode("utf-8"))
    return path
