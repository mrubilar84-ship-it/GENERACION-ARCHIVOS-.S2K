import unittest

from s2k.sections import (
    check_weight,
    i_section,
    parse_designation,
    polygon_properties,
    props_i_shape,
    section_from_polygon,
)


def rect_ring(w, h):
    return [([(0, 0), (w, 0), (w, h), (0, h)], 1)]


def i_ring(d, b, tf, tw):
    """Contorno de un perfil I centrado en el origen, sin filetes (metros)."""
    pts = [
        (-b / 2, -d / 2), (b / 2, -d / 2), (b / 2, -d / 2 + tf), (tw / 2, -d / 2 + tf),
        (tw / 2, d / 2 - tf), (b / 2, d / 2 - tf), (b / 2, d / 2), (-b / 2, d / 2),
        (-b / 2, d / 2 - tf), (-tw / 2, d / 2 - tf), (-tw / 2, -d / 2 + tf), (-b / 2, -d / 2 + tf),
    ]
    return [(pts, 1)]


class SectionTests(unittest.TestCase):
    def test_designation_parsing(self):
        self.assertEqual(parse_designation("Viga HN Soldado:HN30x92.2"), ("HN30x92.2", 92.2))
        self.assertEqual(parse_designation("Viga XL Plegado:XL16x11.92"), ("XL16x11.92", 11.92))
        self.assertIsNone(parse_designation("Muro genérico"))

    def test_i_shape_area_and_weight_match_designation(self):
        spec = i_section("HN30x92.2", 0.30, 0.30, 0.016, 0.008)
        self.assertAlmostEqual(spec.area, 0.011744, places=9)
        check_weight(spec, 92.2)
        self.assertEqual(spec.warnings, [])

    def test_weight_mismatch_is_reported(self):
        spec = i_section("HN30x92.2", 0.30, 0.30, 0.020, 0.012)
        check_weight(spec, 92.2)
        self.assertTrue(any("peso calculado" in w for w in spec.warnings))

    def test_rectangle_polygon_properties(self):
        P = polygon_properties(rect_ring(0.2, 0.1))
        self.assertAlmostEqual(P["A"], 0.02, places=12)
        # ancho 0,2 m y alto 0,1 m: inercia mayor alrededor del eje horizontal = 0,1 * 0,2^3 / 12
        self.assertAlmostEqual(P["I1"], 0.1 * 0.2**3 / 12, places=12)
        self.assertAlmostEqual(P["I2"], 0.2 * 0.1**3 / 12, places=12)

    def test_i_shape_props_match_polygon(self):
        d, b, tf, tw = 0.25, 0.25, 0.008, 0.006
        exact = polygon_properties(i_ring(d, b, tf, tw))
        props = props_i_shape(d, b, tf, tw)
        self.assertAlmostEqual(exact["A"], props["A"], places=10)
        self.assertAlmostEqual(max(exact["I1"], exact["I2"]), props["I33"], delta=props["I33"] * 1e-6)

    def test_angle_is_recognised_from_polygon(self):
        t, leg = 0.006, 0.10
        # L de lados rectos: dos rectángulos unidos
        L = [([(0, 0), (leg, 0), (leg, t), (t, t), (t, leg), (0, leg)], 1)]
        spec = section_from_polygon("L10x8.96", L, "L10x8.96")
        self.assertEqual(spec.shape, "Angle")
        self.assertAlmostEqual(spec.dims["tf"], t, places=6)

    def test_i_family_polygon_becomes_i_shape(self):
        ring = i_ring(0.200, 0.100, 0.006, 0.005)
        spec = section_from_polygon("IN20x16.8", ring, "IN20x16.8")
        self.assertEqual(spec.shape, "I/Wide Flange")
        self.assertAlmostEqual(spec.dims["t3"], 0.200, places=4)
        self.assertAlmostEqual(spec.dims["tf"], 0.006, places=3)
        self.assertAlmostEqual(spec.dims["tw"], 0.005, places=3)

    def test_unknown_family_stays_general(self):
        spec = section_from_polygon("XX", rect_ring(0.2, 0.1), "XX1x1")
        self.assertEqual(spec.shape, "General")
        self.assertTrue(spec.warnings)


if __name__ == "__main__":
    unittest.main()
