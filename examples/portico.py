"""Ejemplo: pórtico plano de dos pisos en acero, exportado a .s2k.

Uso:
    python examples/portico.py [salida.s2k]
"""

import sys
from pathlib import Path

# Permite ejecutar el script directamente desde la raíz del repositorio.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from s2k import FrameSection, Material, Model, write  # noqa: E402


def build_portico(bay_width: float = 6.0, story_height: float = 3.5, bays: int = 2, stories: int = 2) -> Model:
    model = Model()
    model.add_material(Material("A992Fy50", e1=199947.96, u12=0.3, unit_weight=76.9729, fy=345000))
    model.add_section(FrameSection("W14X30", "A992Fy50", "I/Wide Flange", t3=0.35, t2=0.17))
    model.add_section(FrameSection("W16X40", "A992Fy50", "I/Wide Flange", t3=0.41, t2=0.18))

    # Nudos: numerados fila por fila, de abajo hacia arriba.
    label = 1
    grid: dict[tuple[int, int], int] = {}
    for level in range(stories + 1):
        for col in range(bays + 1):
            model.add_joint(label, col * bay_width, 0.0, level * story_height)
            grid[(col, level)] = label
            label += 1

    # Apoyos en la base.
    for col in range(bays + 1):
        model.add_restraint(grid[(col, 0)])

    # Columnas y vigas.
    frame_id = 1
    for level in range(stories):
        for col in range(bays + 1):
            model.add_frame(f"C{frame_id}", grid[(col, level)], grid[(col, level + 1)], "W14X30")
            frame_id += 1
    for level in range(1, stories + 1):
        for col in range(bays):
            model.add_frame(f"V{frame_id}", grid[(col, level)], grid[(col + 1, level)], "W16X40")
            frame_id += 1

    return model


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "portico.s2k"
    print(write(build_portico(), output))
