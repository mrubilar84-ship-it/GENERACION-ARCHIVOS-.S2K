import unittest

from s2k.model import Model
from s2k.sections import i_section


def make_model():
    m = Model(snap_tol=0.01, near_tol=0.10, cross_tol=0.01)
    m.add_section(i_section("HN30x92.2", 0.30, 0.30, 0.016, 0.008))
    return m


class ModelTests(unittest.TestCase):
    def test_nodes_within_snap_tolerance_merge(self):
        m = make_model()
        a = m.node(0, 0, 0)
        b = m.node(0.004, 0, 0)
        c = m.node(1, 0, 0)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_zero_length_frame_is_rejected(self):
        m = make_model()
        a = m.node(0, 0, 0)
        b = m.node(0.005, 0, 0)  # se fusiona con a
        self.assertIsNone(m.add_frame(a, b, "HN30x92.2"))

    def test_beam_is_split_at_interior_node(self):
        m = make_model()
        m.add_frame(m.node(0, 0, 3), m.node(6, 0, 3), "HN30x92.2")
        m.node(3, 0, 3)  # nudo de una columna que llega a la viga
        splits = m.split_at_nodes()
        self.assertEqual(splits, 1)
        self.assertEqual(len(m.frames), 2)
        self.assertAlmostEqual(sum(m.length(l) for l in m.frames), 6.0, places=9)

    def test_isolated_member_is_reported(self):
        m = make_model()
        m.add_frame(m.node(0, 0, 0), m.node(4, 0, 0), "HN30x92.2")
        m.add_frame(m.node(10, 0, 0), m.node(14, 0, 0), "HN30x92.2")
        m.add_frame(m.node(0, 0, 0), m.node(0, 0, 3), "HN30x92.2")
        codes = [i.code for i in m.checks()]
        self.assertIn("COMPONENTES_SEPARADOS", codes)
        self.assertEqual(len(m.components()), 2)

    def test_orphan_node_is_reported(self):
        m = make_model()
        m.node(5, 5, 5)
        self.assertIn("NUDO_DESCONECTADO", [i.code for i in m.checks()])

    def test_free_end_attaches_to_perpendicular_member_interior(self):
        m = make_model()
        m.add_frame(m.node(0, 0, 0), m.node(0, 0, 4), "HN30x92.2")
        # viga que termina a 10 cm del eje de la columna (dentro del alcance: radio + semialtura)
        m.add_frame(m.node(0.10, 0, 2), m.node(3, 0, 2), "HN30x92.2")
        moved, _ = m.attach_free_ends(radius=0.15)
        self.assertGreaterEqual(moved, 1)
        comps = m.components()
        self.assertEqual(len(comps), 1)

    def test_parallel_members_do_not_join_on_their_interior(self):
        m = make_model()
        m.add_frame(m.node(0, 0, 0), m.node(4, 0, 0), "HN30x92.2")
        m.add_frame(m.node(0.5, 0.05, 0), m.node(3.5, 0.05, 0), "HN30x92.2")
        m.attach_free_ends(radius=0.15)
        self.assertEqual(len(m.components()), 2)

    def test_duplicate_frames_are_removed(self):
        m = make_model()
        a, b = m.node(0, 0, 0), m.node(4, 0, 0)
        m.add_frame(a, b, "HN30x92.2", "g1")
        m.add_frame(a, b, "HN30x92.2", "g2")
        removed = m.remove_duplicate_frames()
        self.assertEqual(removed, ["g2"])
        self.assertEqual(len(m.frames), 1)

    def test_near_miss_nodes_are_reported_not_merged(self):
        m = make_model()
        m.add_frame(m.node(0, 0, 0), m.node(4, 0, 0), "HN30x92.2")
        m.add_frame(m.node(4.05, 0, 0), m.node(8, 0, 0), "HN30x92.2")
        codes = [i.code for i in m.checks()]
        self.assertIn("NUDOS_CERCANOS", codes)

    def test_snap_nodes_to_frame_axis(self):
        m = make_model()
        m.add_frame(m.node(0, 0, 0), m.node(6, 0, 0), "HN30x92.2")
        m.add_frame(m.node(3, 0.015, 0), m.node(3, 3, 0), "HN30x92.2")  # nudo a 1,5 cm del eje
        moved, _ = m.snap_nodes_to_frames(tol=0.02)
        self.assertGreaterEqual(moved, 1)
        self.assertEqual(len(m.components()), 1)

    def test_restraint_on_unknown_node_is_rejected(self):
        m = make_model()
        with self.assertRaises(ValueError):
            m.restrain(99)


if __name__ == "__main__":
    unittest.main()
