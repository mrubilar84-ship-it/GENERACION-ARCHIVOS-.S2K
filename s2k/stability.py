"""Chequeo de estabilidad sin SAP: matriz de rigidez 3D y conteo de modos de mecanismo.

Local DOFs por nudo: u1 u2 u3 r1 r2 r3 (índices 0..5). Liberaciones: r1 = torsión (3),
r2 = M2 (4), r3 = M3 (5). Con E = 1, la matriz sirve para contar mecanismos, no para resultados.
"""

from __future__ import annotations

import numpy as np

from .model import Model

T_IDX, M2_IDX, M3_IDX = 3, 4, 5
TOL = 1e-9


def section_stiffness(model: Model, name: str) -> tuple[float, float, float, float]:
    """(A, I2, I3, J) para la sección; si no hay propiedades (ángulos), aproximación por dimensiones."""
    spec = model.sections[name]
    if spec.props:
        p = spec.props
        return p["A"], p["I22"], p["I33"], max(p["J"], 1e-12)
    d = spec.dims
    t = d["tf"]
    h, w = d["t3"], d["t2"]
    A = (h + w - t) * t
    I = t * h**3 / 12
    return A, I, I, t**3 * (h + w) / 3


def local_stiffness(L: float, A: float, I2: float, I3: float, J: float, E: float = 1.0, G: float = 0.4) -> np.ndarray:
    k = np.zeros((12, 12))
    a = E * A / L
    k[0, 0] = k[6, 6] = a
    k[0, 6] = k[6, 0] = -a
    g = G * J / L
    k[3, 3] = k[9, 9] = g
    k[3, 9] = k[9, 3] = -g
    # plano 1-2 (v, r3) con I3
    c = E * I3 / L**3
    idx = [1, 5, 7, 11]
    blk = c * np.array([
        [12, 6 * L, -12, 6 * L],
        [6 * L, 4 * L * L, -6 * L, 2 * L * L],
        [-12, -6 * L, 12, -6 * L],
        [6 * L, 2 * L * L, -6 * L, 4 * L * L],
    ])
    k[np.ix_(idx, idx)] += blk
    # plano 1-3 (w, r2) con I2; signos de la rotación r2
    c = E * I2 / L**3
    idx = [2, 4, 8, 10]
    blk = c * np.array([
        [12, -6 * L, -12, -6 * L],
        [-6 * L, 4 * L * L, 6 * L, 2 * L * L],
        [-12, 6 * L, 12, 6 * L],
        [-6 * L, 2 * L * L, 6 * L, 4 * L * L],
    ])
    k[np.ix_(idx, idx)] += blk
    return k


def condense(k: np.ndarray, released: set[int]) -> np.ndarray:
    """Condensación estática de los DOFs locales liberados (articulaciones)."""
    if not released:
        return k
    keep = [i for i in range(12) if i not in released]
    rel = sorted(released)
    krr = k[np.ix_(rel, rel)]
    kkr = k[np.ix_(keep, rel)]
    out = np.zeros((12, 12))
    out[np.ix_(keep, keep)] = k[np.ix_(keep, keep)] - kkr @ np.linalg.pinv(krr) @ kkr.T
    return out


def _rotation(d: np.ndarray) -> np.ndarray:
    e1 = d / np.linalg.norm(d)
    ref = np.array([1.0, 0, 0]) if abs(e1[2]) > 0.99 else np.array([0, 0, 1.0])
    e2 = np.cross(ref, e1)
    e2 /= np.linalg.norm(e2)
    e3 = np.cross(e1, e2)
    return np.array([e1, e2, e3])


def count_mechanisms(model: Model, releases: dict[tuple[int, str], set[int]],
                     fixed_nodes: set[int], E: float = 1.0) -> int:
    """Número de modos de mecanismo (autovalores ~0) con los apoyos dados.

    releases: {(frame_label, 'i' | 'j'): {índices locales liberados}}.
    """
    node_ids = sorted(model.nodes)
    pos = {n: 6 * k for k, n in enumerate(node_ids)}
    N = 6 * len(node_ids)
    K = np.zeros((N, N))
    for label, f in model.frames.items():
        P, Q = np.array(model.nodes[f.i]), np.array(model.nodes[f.j])
        d = Q - P
        L = float(np.linalg.norm(d))
        A, I2, I3, J = section_stiffness(model, f.section)
        rel = set()
        rel |= releases.get((label, "i"), set())
        rel |= {x + 6 for x in releases.get((label, "j"), set())}
        k = condense(local_stiffness(L, A, I2, I3, J, E), rel)
        R = _rotation(d)
        T = np.kron(np.eye(4), R)
        kg = T.T @ k @ T
        dofs = list(range(pos[f.i], pos[f.i] + 6)) + list(range(pos[f.j], pos[f.j] + 6))
        K[np.ix_(dofs, dofs)] += kg
    fixed = {d for n in fixed_nodes for d in range(pos[n], pos[n] + 6)}
    free = [d for d in range(N) if d not in fixed]
    if not free:
        return 0
    Kf = K[np.ix_(free, free)]
    scale = np.max(np.abs(Kf.diagonal())) if Kf.size else 1.0
    lam = np.linalg.eigvalsh(Kf)
    return int(np.sum(np.abs(lam) <= TOL * scale))
