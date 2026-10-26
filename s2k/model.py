"""Modelo en memoria de una estructura, independiente del formato de salida."""

from dataclasses import dataclass, field
import math


@dataclass
class Joint:
    label: int
    x: float
    y: float
    z: float


@dataclass
class Material:
    name: str
    e1: float  # módulo de elasticidad
    u12: float  # razón de Poisson
    unit_weight: float
    fy: float = 0.0


@dataclass
class FrameSection:
    name: str
    material: str
    shape: str  # p. ej. "Rectangular", "I/Wide Flange"
    t3: float  # altura de la sección
    t2: float  # ancho de la sección


@dataclass
class Frame:
    label: str
    joint_i: int
    joint_j: int
    section: str


@dataclass
class Restraint:
    joint: int
    fixed: tuple[bool, bool, bool, bool, bool, bool] = (True,) * 6


@dataclass
class Model:
    joints: dict[int, Joint] = field(default_factory=dict)
    materials: dict[str, Material] = field(default_factory=dict)
    sections: dict[str, FrameSection] = field(default_factory=dict)
    frames: list[Frame] = field(default_factory=list)
    restraints: list[Restraint] = field(default_factory=list)

    def add_joint(self, label: int, x: float, y: float, z: float) -> Joint:
        if label in self.joints:
            raise ValueError(f"El nudo {label} ya existe")
        joint = Joint(label, x, y, z)
        self.joints[label] = joint
        return joint

    def add_material(self, material: Material) -> None:
        self.materials[material.name] = material

    def add_section(self, section: FrameSection) -> None:
        if section.material not in self.materials:
            raise ValueError(f"Material desconocido: {section.material}")
        self.sections[section.name] = section

    def add_frame(self, label: str, joint_i: int, joint_j: int, section: str) -> Frame:
        if joint_i not in self.joints or joint_j not in self.joints:
            raise ValueError(f"Barra {label}: nudo inexistente")
        if section not in self.sections:
            raise ValueError(f"Barra {label}: sección desconocida {section}")
        frame = Frame(label, joint_i, joint_j, section)
        self.frames.append(frame)
        return frame

    def add_restraint(self, joint: int, fixed: tuple[bool, ...] = (True,) * 6) -> None:
        if joint not in self.joints:
            raise ValueError(f"Apoyo en nudo inexistente: {joint}")
        self.restraints.append(Restraint(joint, fixed))

    def frame_length(self, frame: Frame) -> float:
        a = self.joints[frame.joint_i]
        b = self.joints[frame.joint_j]
        return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
