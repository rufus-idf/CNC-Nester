import unittest

from offcut_stock import build_offcut_stock_rows, extract_spreadsheet_id


class OffcutStockTests(unittest.TestCase):
    def test_extract_spreadsheet_id_from_url(self):
        value = "https://docs.google.com/spreadsheets/d/1-qS6gWekGtEhjczboAyAShJHHamK0ZuVlR7CFbubxxo/edit?gid=0#gid=0"
        self.assertEqual(extract_spreadsheet_id(value), "1-qS6gWekGtEhjczboAyAShJHHamK0ZuVlR7CFbubxxo")

    def test_extract_spreadsheet_id_accepts_raw_id(self):
        raw_id = "1-qS6gWekGtEhjczboAyAShJHHamK0ZuVlR7CFbubxxo"
        self.assertEqual(extract_spreadsheet_id(raw_id), raw_id)

    def test_build_offcut_stock_rows_builds_expected_tabs(self):
        layout = {"sheet_w": 1000.0, "sheet_h": 500.0, "margin": 10.0}
        sheet = {"sheet_index": 1}
        reusable = [{"x": 10.0, "y": 20.0, "width": 300.0, "height": 200.0, "area": 60000.0}]

        rows = build_offcut_stock_rows(
            layout,
            sheet,
            reusable,
            material="MDF",
            thickness_mm=18,
            location="Rack-A1",
            sheet_origin_job="JOB-123",
            captured_at_utc="2026-04-12T14:33:09Z",
        )

        self.assertEqual(set(rows.keys()), {"offcut_inventory", "offcut_shapes", "offcut_events", "offcut_previews"})
        self.assertEqual(len(rows["offcut_inventory"]), 1)
        self.assertEqual(len(rows["offcut_shapes"]), 1)
        self.assertEqual(len(rows["offcut_events"]), 1)
        self.assertEqual(len(rows["offcut_previews"]), 1)

        inventory = rows["offcut_inventory"][0]
        self.assertEqual(inventory["shape_type"], "RECT")
        self.assertEqual(inventory["material"], "MDF")
        self.assertEqual(inventory["bbox_w_mm"], 300.0)
        self.assertEqual(inventory["bbox_h_mm"], 200.0)

        shape = rows["offcut_shapes"][0]
        self.assertEqual(shape["bbox_x_mm"], 10.0)
        self.assertEqual(shape["bbox_y_mm"], 20.0)
        self.assertIn("[[10.0, 20.0]", shape["vertices_json"])


if __name__ == "__main__":
    unittest.main()
