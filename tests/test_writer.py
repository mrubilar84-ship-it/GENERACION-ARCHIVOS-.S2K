import unittest

from s2k.model import Model
from s2k.sections import angle_section, i_section
from s2k.writer import render


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.m = Model(units="Tonf, m, C")
        self.m.add_section(i_section("HN30x92.2", 0.30, 0.30, 0.016, 0.008, designation="HN30x92.2"))
        self.m.add_section(angle_section("L10x8.96", 0.10, 0.10, 0.006, designation="L10x8.96"))
        a = self.m.node(0, 0, 0)
        b = self.m.node(0, 0, 3)
        c = self.m.node(3, 0, 3)
        self.m.add_frame(a, b, "HN30x92.2", "guid-1")
        self.m.add_frame(b, c, "L10x8.96", "guid-2")
        self.m.restrain(a)
        self.text = render(self.m)

    def test_uses_crlf_only(self):
        self.assertIn("\r\n", self.text)
        self.assertEqual(self.text.count("\n"), self.text.count("\r\n"))

    def test_ends_with_end_table_data(self):
        self.assertTrue(self.text.rstrip("\r\n").endswith("END TABLE DATA"))

    def test_quotes_values_with_spaces_and_slashes(self):
        self.assertIn('Shape="I/Wide Flange"', self.text)
        self.assertIn('CurrUnits="Tonf, m, C"', self.text)

    def test_connectivity_and_assignments(self):
        self.assertIn('TABLE:  "CONNECTIVITY - FRAME"', self.text)
        self.assertIn("Frame=1   JointI=1   JointJ=2", self.text)
        self.assertIn("Frame=2   SectionType=Angle", self.text)

    def test_restraint_written(self):
        self.assertIn("Joint=1   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes", self.text)

    def test_unknown_material_is_rejected(self):
        self.m.sections["HN30x92.2"].material = "XX"
        with self.assertRaises(ValueError):
            render(self.m)


if __name__ == "__main__":
    unittest.main()
