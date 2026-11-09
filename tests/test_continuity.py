import unittest

from s2k.continuity import plan
from s2k.model import Model
from s2k.sections import i_section
from s2k.stability import count_mechanisms
from s2k.writer import render


def portal():
    """Dos columnas, viga continua que recibe una viga secundaria en su centro."""
    m = Model()
    m.add_section(i_section("HN30", 0.30, 0.30, 0.016, 0.008))
    m.add_section(i_section("HN25", 0.25, 0.25, 0.008, 0.006))
    a, b = m.node(0, 0, 0), m.node(0, 0, 3)
    c, d = m.node(6, 0, 3), m.node(6, 0, 0)
    m.add_frame(a, b, "HN30", "col1")
    m.add_frame(d, c, "HN30", "col2")
    m.add_frame(b, c, "HN30", "viga")
    f = m.node(3, 2, 3)
    m.add_frame(f, m.node(3, 0, 3), "HN25", "sec")
    m.split_at_nodes()
    return m


class ContinuityTests(unittest.TestCase):
    def test_collinear_segments_through_a_joint_form_one_bar(self):
        p = plan(portal(), releases=False)
        viga = [of for of in p.frames if of.section == "HN30" and len(of.segments) > 1]
        self.assertEqual(len(viga), 1)
        self.assertEqual(len(viga[0].segments), 2)

    def test_columns_are_never_released(self):
        p = plan(portal(), releases=True)
        cols = [of for of in p.frames if (of.i, of.j) in {(1, 2), (4, 3)}]
        self.assertTrue(cols)
        for of in cols:
            self.assertFalse(of.releases)

    def test_releases_keep_structure_stable(self):
        p = plan(portal(), releases=True)
        self.assertEqual(p.mechanisms_rigid, 0)
        self.assertEqual(p.mechanisms_final, 0)
        self.assertGreater(p.releases_applied, 0)

    def test_pinned_beam_end_does_not_create_mechanism_when_it_is_the_only_brace(self):
        m = Model()
        m.add_section(i_section("HN30", 0.30, 0.30, 0.016, 0.008))
        a, b = m.node(0, 0, 0), m.node(0, 0, 3)
        m.add_frame(a, b, "HN30", "col")
        # una barra colgando de un solo extremo: liberar su nudo sería un péndulo
        m.add_frame(b, m.node(3, 0, 3), "HN30", "viga")
        p = plan(m, releases=True)
        self.assertEqual(p.mechanisms_final, p.mechanisms_rigid)

    def test_unsupported_structure_reports_mechanisms(self):
        m = Model()
        m.add_section(i_section("HN30", 0.30, 0.30, 0.016, 0.008))
        m.add_frame(m.node(0, 0, 0), m.node(4, 0, 0), "HN30", "solo")
        self.assertGreater(count_mechanisms(m, {}, set()), 0)
        self.assertEqual(count_mechanisms(m, {}, {1, 2}), 0)

    def test_writer_emits_releases_automesh_and_special_joints(self):
        m = portal()
        p = plan(m, releases=True)
        text = render(m, "portal", p)
        self.assertIn('TABLE:  "FRAME RELEASE ASSIGNMENTS 1 - GENERAL"', text)
        self.assertIn("AutoMesh=Yes   AtJoints=Yes   AtFrames=No", text)
        # el nudo 6 es extremo de la viga secundaria: debe quedar SpecialJt=No
        self.assertIn("Joint=6   CoordSys=GLOBAL   CoordType=Cartesian   XorR=3   Y=0   Z=3   SpecialJt=No", text)
        self.assertTrue(text.count("\n") == text.count("\r\n"))


class FuseTests(unittest.TestCase):
    def test_near_nodes_are_fused_and_reported(self):
        m = Model(snap_tol=0.01)
        m.add_section(i_section("HN30", 0.30, 0.30, 0.016, 0.008))
        a, b = m.node(0, 0, 0), m.node(4, 0, 0)
        m.add_frame(a, b, "HN30", "viga")
        c = m.node(4.05, 0.0, 3.0)  # una columna a 5 cm del extremo de la viga
        m.add_frame(c, m.node(4.05, 0, 0), "HN30", "col")
        pairs, moved = m.fuse_near(0.10)
        self.assertGreaterEqual(pairs, 1)
        self.assertLessEqual(moved, 0.05 + 1e-9)
        self.assertEqual(len(m.components()), 1)


if __name__ == "__main__":
    unittest.main()
