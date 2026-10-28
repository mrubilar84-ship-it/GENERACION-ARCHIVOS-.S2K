"""Prueba de extremo a extremo con un IFC real.

Se ejecuta solo si se indica la ruta:
    S2K_TEST_IFC=/ruta/al/archivo.ifc python -m unittest tests.test_ifc
"""

import importlib.util
import os
import unittest
from collections import Counter

IFC = os.environ.get("S2K_TEST_IFC")

HAVE_IFC = importlib.util.find_spec("ifcopenshell") is not None


@unittest.skipUnless(IFC and HAVE_IFC, "requiere S2K_TEST_IFC y ifcopenshell")
class CmzIfcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from s2k.ifc import build
        cls.model, cls.report = build(IFC)

    def test_member_counts(self):
        self.assertEqual(self.report.info["classes"], {"IfcBeam": 80, "IfcColumn": 14})

    def test_sections_match_designations(self):
        names = set(self.report.sections)
        self.assertTrue({"HN30x92.2", "HN25x42.4", "L10x8.96", "L80x80x5", "IN20x16.8"} <= names)
        for s in self.report.sections.values():
            weight_warnings = [w for w in s.warnings if w.startswith("peso")]
            self.assertEqual(weight_warnings, [], s.name)

    def test_all_frames_reference_existing_nodes(self):
        for f in self.model.frames.values():
            self.assertIn(f.i, self.model.nodes)
            self.assertIn(f.j, self.model.nodes)
            self.assertNotEqual(f.i, f.j)

    def test_only_expected_connectivity_errors(self):
        # En el IFC de referencia hay una viga sin ningún elemento conectado; debe reportarse, no ocultarse.
        errors = [i for i in self.report.issues if i.severity == "error"]
        self.assertTrue(all(i.code == "COMPONENTES_SEPARADOS" for i in errors), errors)

    def test_geometry_is_not_forced_to_grid_by_default(self):
        zs = {round(z, 3) for _, _, z in self.model.nodes.values()}
        self.assertTrue(any(abs(z - 7.918) < 0.005 for z in zs), "la cota medida de la cubierta debe conservarse")
        self.assertFalse(any(abs(z - 7.9) < 1e-6 for z in zs), "no debe aplicarse la cota regular 7,90")

    def test_regular_grid_is_detected(self):
        xs = [a.value for a in self.report.grid.x]
        ys = [a.value for a in self.report.grid.y]
        self.assertEqual(xs, [0.0, 3.0, 6.0, 9.0, 12.0, 15.0, 18.0])
        self.assertEqual(ys, [0.0, 5.1])

    def test_xl_members_are_single_l_without_duplicates(self):
        sections = {f.section for f in self.model.frames.values()}
        self.assertIn("L80x80x5", sections)
        self.assertNotIn("XL16x11.92", sections)
        xl_frames = [f for f in self.model.frames.values() if f.section == "L80x80x5"]
        self.assertEqual({f.angle for f in xl_frames}, {0.0})
        self.assertEqual(len({(min(f.i, f.j), max(f.i, f.j)) for f in xl_frames}), len(xl_frames))

    def test_no_duplicate_frames_left(self):
        keys = Counter((tuple(sorted((f.i, f.j))), f.section, f.angle) for f in self.model.frames.values())
        self.assertTrue(all(v == 1 for v in keys.values()))


if __name__ == "__main__":
    unittest.main()
