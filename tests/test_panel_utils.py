import unittest

from panel_utils import coerce_bool, normalize_panels, panels_to_editor_rows, apply_editor_rows, parse_tooling_json_cell


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



    def test_normalize_panels_preserves_tooling_payload(self):
        panels = [{
            "Label": "Machined",
            "Width": 1000,
            "Length": 500,
            "Qty": 1,
            "Grain?": False,
            "Material": "MDF",
            "Tooling": {"coord_mode": "normalized", "toolpath_segments": []},
        }]
        normalized = normalize_panels(panels)
        self.assertIn("Tooling", normalized[0])
        self.assertEqual(normalized[0]["Tooling"]["coord_mode"], "normalized")



    def test_parse_tooling_json_cell_handles_sheet_wrapped_escaped_json(self):
        raw = '"{\n  ""panel_thickness"": 18,\n  ""borings"": [{""x"": 0.5, ""y"": 0.5}]\n}"'
        parsed = parse_tooling_json_cell(raw)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["panel_thickness"], 18)
        self.assertEqual(parsed["borings"][0]["x"], 0.5)

    def test_apply_editor_rows_swaps_length_and_width_when_requested(self):
        rows = panels_to_editor_rows([
            {"Label": "Part A", "Width": 200, "Length": 800, "Qty": 1, "Grain?": False, "Material": "X"}
        ])
        rows[0]["Swap L↔W"] = True

        normalized_panels, normalized_editor_rows = apply_editor_rows(rows)

        self.assertEqual(normalized_panels[0]["Width"], 800)
        self.assertEqual(normalized_panels[0]["Length"], 200)
        self.assertFalse(normalized_editor_rows[0]["Swap L↔W"])


if __name__ == "__main__":
    unittest.main()
