import unittest

from s2k.grid import SnapStats, detect_grid, snap_point


def endpoints_on_lines(xs, ys, zs, reps=4):
    """Puntos de prueba: cada combinación de línea se repite `reps` veces (simula soporte de extremos)."""
    pts = []
    for x in xs:
        for y in ys:
            for z in zs:
                pts += [(x, y, z)] * reps
    return pts


class GridTests(unittest.TestCase):
    def test_spacing_rounds_to_closed_dimension(self):
        # 5,05 m medidos entre columnas → 5,10 m con paso de 0,10
        pts = endpoints_on_lines([0.0, 5.05], [0.0], [0.0])
        grid = detect_grid(pts, step_xy=0.10, step_z=0.05)
        self.assertEqual([a.value for a in grid.x], [0.0, 5.1])

    def test_regular_spacings_accumulate_without_drift(self):
        xs = [0.0, 3.02, 6.01, 9.03]
        grid = detect_grid(endpoints_on_lines(xs, [0.0], [0.0]), step_xy=0.10, step_z=0.05)
        self.assertEqual([round(a.value, 6) for a in grid.x], [0.0, 3.0, 6.0, 9.0])

    def test_lines_with_little_support_are_ignored(self):
        pts = endpoints_on_lines([0.0, 6.0], [0.0], [0.0]) + [(0.15, 0.0, 0.0)] * 2
        grid = detect_grid(pts, step_xy=0.10, step_z=0.05, min_support=4)
        self.assertEqual([a.value for a in grid.x], [0.0, 6.0])

    def test_snap_moves_point_within_tolerance_only(self):
        pts = endpoints_on_lines([0.0, 5.05], [0.0], [0.0])
        grid = detect_grid(pts, step_xy=0.10, step_z=0.05, tol_xy=0.10)
        stats = SnapStats()
        self.assertEqual(snap_point((5.04, 0.02, 0.01), grid, stats)[0], 5.1)
        self.assertEqual(snap_point((2.5, 0.0, 0.0), grid, stats)[0], 2.5)
        self.assertEqual(stats.unchanged, 1)
        self.assertGreater(stats.coordinates, 0)

    def test_z_levels_use_z_step(self):
        pts = endpoints_on_lines([0.0], [0.0], [0.0, 2.86])
        grid = detect_grid(pts, step_xy=0.10, step_z=0.05)
        self.assertEqual([a.value for a in grid.z], [0.0, 2.85])


if __name__ == "__main__":
    unittest.main()
