import unittest
from unittest.mock import patch

from offcut_utils import calculate_sheet_offcuts, calculate_l_mix_offcuts, build_sheet_usage_heatmap, build_sheet_offcut_preview


class OffcutUtilsTests(unittest.TestCase):
    def test_calculate_sheet_offcuts_empty_sheet(self):
        layout = {
            "sheet_w": 1000.0,
            "sheet_h": 500.0,
            "margin": 10.0,
        }
        sheet = {"parts": []}

        result = calculate_sheet_offcuts(layout, sheet, min_width=0.0, min_height=0.0, min_area=0.0)

        self.assertEqual(result["utilization_pct"], 0.0)
        self.assertEqual(len(result["reusable_offcuts"]), 1)
        self.assertEqual(result["reusable_offcuts"][0]["width"], 980.0)
        self.assertEqual(result["reusable_offcuts"][0]["height"], 480.0)

    def test_calculate_sheet_offcuts_reports_expected_utilization(self):
        layout = {
            "sheet_w": 1000.0,
            "sheet_h": 500.0,
            "margin": 10.0,
        }
        sheet = {
            "parts": [
                {"x": 10.0, "y": 10.0, "w": 200.0, "h": 100.0},
                {"x": 220.0, "y": 10.0, "w": 300.0, "h": 100.0},
            ]
        }

        result = calculate_sheet_offcuts(layout, sheet, min_width=100.0, min_height=100.0, min_area=10000.0)

        self.assertAlmostEqual(result["used_area"], 50000.0)
        self.assertAlmostEqual(result["interior_area"], 470400.0)
        self.assertAlmostEqual(result["utilization_pct"], 10.63)
        self.assertGreaterEqual(len(result["reusable_offcuts"]), 1)

    def test_calculate_sheet_offcuts_filters_small_scraps(self):
        layout = {
            "sheet_w": 500.0,
            "sheet_h": 500.0,
            "margin": 0.0,
        }
        sheet = {
            "parts": [
                {"x": 0.0, "y": 0.0, "w": 490.0, "h": 490.0},
            ]
        }

        result = calculate_sheet_offcuts(layout, sheet, min_width=20.0, min_height=20.0, min_area=400.0)

        self.assertEqual(result["reusable_offcuts"], [])


    def test_build_sheet_offcut_preview_returns_parts_and_free_regions(self):
        layout = {
            "sheet_w": 200.0,
            "sheet_h": 100.0,
            "margin": 0.0,
        }
        sheet = {
            "sheet_index": 0,
            "parts": [
                {"x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0},
            ],
        }

        preview = build_sheet_offcut_preview(layout, sheet)

        self.assertEqual(preview["usable"]["width"], 200.0)
        self.assertEqual(preview["usable"]["height"], 100.0)
        self.assertEqual(len(preview["parts"]), 1)
        self.assertEqual(len(preview["free_regions"]), 1)
        self.assertEqual(preview["free_regions"][0]["x"], 100.0)
        self.assertEqual(preview["free_regions"][0]["width"], 100.0)


    def test_calculate_l_mix_offcuts_detects_l_shape(self):
        layout = {
            "sheet_w": 200.0,
            "sheet_h": 200.0,
            "margin": 0.0,
        }
        sheet = {
            "sheet_index": 0,
            "parts": [
                {"x": 100.0, "y": 100.0, "w": 100.0, "h": 100.0},
            ],
        }

        result = calculate_l_mix_offcuts(layout, sheet, min_width=20.0, min_height=20.0, min_area=100.0)

        self.assertTrue(any(r.get("shape_type") == "L" for r in result))


    def test_calculate_l_mix_offcuts_filters_l_shape_with_small_tail_edge(self):
        layout = {
            "sheet_w": 120.0,
            "sheet_h": 120.0,
            "margin": 0.0,
        }
        sheet = {
            "sheet_index": 0,
            "parts": [
                {"x": 0.0, "y": 0.0, "w": 114.0, "h": 114.0},
            ],
        }

        result = calculate_l_mix_offcuts(layout, sheet, min_width=50.0, min_height=10.0, min_area=100.0)

        self.assertFalse(any(r.get("shape_type") == "L" for r in result))


    def test_calculate_l_mix_offcuts_can_form_second_l_shape_across_kerf_gaps(self):
        layout = {
            "sheet_w": 2440.0,
            "sheet_h": 1220.0,
            "margin": 10.0,
        }
        sheet = {
            "sheet_index": 0,
            "parts": [
                {"x": 10.0, "y": 10.0, "w": 1914.0, "h": 386.0},
                {"x": 10.0, "y": 402.0, "w": 1078.0, "h": 136.0},
                {"x": 1094.0, "y": 402.0, "w": 1064.0, "h": 136.0},
                {"x": 10.0, "y": 544.0, "w": 741.0, "h": 136.0},
                {"x": 757.0, "y": 544.0, "w": 735.0, "h": 136.0},
                {"x": 1498.0, "y": 544.0, "w": 747.0, "h": 136.0},
                {"x": 10.0, "y": 686.0, "w": 741.0, "h": 136.0},
            ],
        }

        result = calculate_l_mix_offcuts(layout, sheet, min_width=60.0, min_height=60.0, min_area=25000.0)

        l_shapes = [r for r in result if r.get("shape_type") == "L"]
        rectangles = [r for r in result if r.get("shape_type") == "RECT"]

        self.assertEqual(len(l_shapes), 2)
        self.assertEqual(len(rectangles), 1)
        self.assertEqual(rectangles[0]["x"], 2245.0)
        self.assertEqual(rectangles[0]["width"], 185.0)
        self.assertGreaterEqual(rectangles[0]["height"], 136.0)
        self.assertGreaterEqual(rectangles[0]["area"], 25160.0)



    def test_calculate_l_mix_offcuts_detects_l_shape_from_four_fragmented_regions(self):
        free_rects = [
            {"x": 80.0, "y": 0.0, "w": 20.0, "h": 40.0},
            {"x": 80.0, "y": 40.0, "w": 20.0, "h": 60.0},
            {"x": 0.0, "y": 80.0, "w": 30.0, "h": 20.0},
            {"x": 30.0, "y": 80.0, "w": 50.0, "h": 20.0},
        ]

        with patch("offcut_utils._usable_sheet_and_parts", return_value=({}, [])):
            with patch("offcut_utils._compute_free_rects", return_value=free_rects):
                result = calculate_l_mix_offcuts({}, {}, min_width=20.0, min_height=20.0, min_area=100.0)

        l_shapes = [r for r in result if r.get("shape_type") == "L"]

        self.assertEqual(len(l_shapes), 1)
        self.assertEqual(l_shapes[0]["width"], 100.0)
        self.assertEqual(l_shapes[0]["height"], 100.0)


    def test_calculate_l_mix_offcuts_rejects_l_shape_if_vertices_leave_free_union(self):
        free_rects = [
            {"x": 0.0, "y": 0.0, "w": 100.0, "h": 40.0},
            {"x": 0.0, "y": 40.0, "w": 40.0, "h": 60.0},
        ]

        with patch("offcut_utils._usable_sheet_and_parts", return_value=({}, [])):
            with patch("offcut_utils._compute_free_rects", return_value=free_rects):
                with patch(
                    "offcut_utils._normalize_polygon_vertices",
                    return_value=[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 40.0], [40.0, 40.0]],
                ):
                    result = calculate_l_mix_offcuts({}, {}, min_width=20.0, min_height=20.0, min_area=100.0)

        self.assertFalse(any(r.get("shape_type") == "L" for r in result))


    def test_build_sheet_usage_heatmap_empty_sheet_cells_are_zero(self):
        layout = {
            "sheet_w": 200.0,
            "sheet_h": 100.0,
            "margin": 0.0,
        }
        sheet = {"parts": []}

        cells = build_sheet_usage_heatmap(layout, sheet, cell_size=100.0)

        self.assertEqual(len(cells), 2)
        self.assertTrue(all(c["usage_pct"] == 0.0 for c in cells))

    def test_build_sheet_usage_heatmap_reports_partial_cell_coverage(self):
        layout = {
            "sheet_w": 200.0,
            "sheet_h": 100.0,
            "margin": 0.0,
        }
        sheet = {
            "parts": [
                {"x": 0.0, "y": 0.0, "w": 50.0, "h": 100.0},
            ]
        }

        cells = build_sheet_usage_heatmap(layout, sheet, cell_size=100.0)

        left = [c for c in cells if c["x"] == 0.0][0]
        right = [c for c in cells if c["x"] == 100.0][0]
        self.assertEqual(left["usage_pct"], 50.0)
        self.assertEqual(right["usage_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
