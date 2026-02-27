import unittest

from offcut_utils import calculate_sheet_offcuts


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


if __name__ == "__main__":
    unittest.main()
