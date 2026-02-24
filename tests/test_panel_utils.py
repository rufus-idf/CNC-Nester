import unittest

from panel_utils import coerce_bool, normalize_panels


class PanelUtilsTests(unittest.TestCase):
    def test_coerce_bool_handles_string_false_correctly(self):
        self.assertFalse(coerce_bool("False"))
        self.assertFalse(coerce_bool("0"))
        self.assertFalse(coerce_bool("no"))

    def test_coerce_bool_handles_string_true_correctly(self):
        self.assertTrue(coerce_bool("True"))
        self.assertTrue(coerce_bool("1"))
        self.assertTrue(coerce_bool("yes"))

    def test_normalize_panels_converts_grain_flags_safely(self):
        panels = [
            {"Label": "A", "Grain?": "False"},
            {"Label": "B", "Grain?": "True"},
            {"Label": "C", "Grain?": 0},
            {"Label": "D", "Grain?": 1},
            {"Label": "E", "Grain?": None},
        ]
        normalized = normalize_panels(panels)
        self.assertEqual([p["Grain?"] for p in normalized], [False, True, False, True, False])


if __name__ == "__main__":
    unittest.main()
