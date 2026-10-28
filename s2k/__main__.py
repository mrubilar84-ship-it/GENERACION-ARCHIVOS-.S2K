"""CLI: python -m s2k modelo.ifc -o salida.s2k [--report reporte.md]."""

from __future__ import annotations

import argparse
from pathlib import Path

from .ifc import build
from .writer import write


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="s2k", description="Genera un .s2k desde un IFC.")
    p.add_argument("ifc", help="archivo .ifc de entrada")
    p.add_argument("-o", "--output", help="archivo .s2k de salida (por defecto: mismo nombre que el IFC)")
    p.add_argument("--report", help="reporte en Markdown (por defecto: junto al .s2k)")
    p.add_argument("--angle", type=float, help="rotación de la grilla en grados (por defecto: automática)")
    p.add_argument("--offset", type=float, nargs=2, metavar=("X", "Y"),
                   help="origen en ejes rotados, metros (por defecto: mínimo de la estructura)")
    p.add_argument("--z0", type=float, help="cota mundo que pasa a Z = 0 (por defecto: mínimo de la estructura)")
    p.add_argument("--snap", type=float, default=0.01, help="tolerancia de fusión de nudos, m (default 0.01)")
    p.add_argument("--near", type=float, default=0.10, help="distancia para avisar nudos cercanos, m (default 0.10)")
    p.add_argument("--join", type=float, default=0.15,
                   help="radio para llevar extremos al eje de otra barra no paralela, m (default 0.15)")
    p.add_argument("--snap-frame", type=float, default=0.02,
                   help="distancia para ajustar un nudo sobre el eje de otra barra, m (default 0.02)")
    p.add_argument("--grid-step", type=float, default=0.10,
                   help="paso para detectar la grilla en planta, m; solo informativo salvo --apply-grid (0 = no detectar)")
    p.add_argument("--apply-grid", action="store_true",
                   help="lleva los extremos de piezas primarias a la grilla regular (por defecto no se ajusta)")
    p.add_argument("--z-step", type=float, default=0.05, help="paso de los niveles Z, m (default 0.05)")
    p.add_argument("--grid-tol", type=float, default=0.10, help="distancia máxima para ajustar a la grilla en planta, m")
    p.add_argument("--z-tol", type=float, default=0.10, help="distancia máxima para ajustar a un nivel, m")
    args = p.parse_args(argv)

    ifc_path = Path(args.ifc)
    out = Path(args.output or ifc_path.with_suffix(".s2k"))
    report_path = Path(args.report or out.with_suffix(".report.md"))

    model, report = build(
        str(ifc_path), angle_deg=args.angle, offset=tuple(args.offset) if args.offset else None,
        z0=args.z0, snap_tol=args.snap, near_tol=args.near, join_radius=args.join, frame_tol=args.snap_frame,
        grid_step=args.grid_step or None, z_step=args.z_step, grid_tol=args.grid_tol, z_tol=args.z_tol,
        apply_grid=args.apply_grid,
        title=ifc_path.name,
    )
    write(model, out)
    report_path.write_text(report.to_markdown(), encoding="utf-8")

    errors = [i for i in report.issues if i.severity == "error"]
    print(f"Barras: {report.frames}  Nudos: {report.nodes}  Secciones: {len(report.sections)}")
    print(f"Observaciones: {len(report.issues)} ({len(errors)} errores)")
    print(f"S2K:    {out}")
    print(f"Reporte: {report_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
