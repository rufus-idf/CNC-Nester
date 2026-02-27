import unittest

from manual_tuning_engine import can_place_part_at, compute_position_grid, legal_bounds, move_part_to


class ManualTuningEngineTests(unittest.TestCase):
    def setUp(self):
        self.layout = {
            "sheet_w": 1000.0,
            "sheet_h": 500.0,
            "margin": 10.0,
            "kerf": 7.0,
            "sheets": [
                {
                    "sheet_index": 0,
                    "parts": [
                        {"id": "A", "rid": "A", "x": 20.0, "y": 20.0, "w": 100.0, "h": 50.0, "rotated": False},
                        {"id": "B", "rid": "B", "x": 200.0, "y": 20.0, "w": 100.0, "h": 50.0, "rotated": False},
                    ],
                }
            ],
        }

    def test_legal_bounds(self):
        part = self.layout["sheets"][0]["parts"][0]
        bounds = legal_bounds(self.layout, part)
        self.assertEqual(bounds["x_min"], 10.0)
        self.assertEqual(bounds["y_min"], 10.0)
        self.assertEqual(bounds["x_max"], 890.0)
        self.assertEqual(bounds["y_max"], 440.0)

    def test_move_part_to_valid(self):
        updated, ok, _ = move_part_to(self.layout, 0, "A", 300.0, 100.0)
        self.assertTrue(ok)
        moved = next(p for p in updated["sheets"][0]["parts"] if p["id"] == "A")
        self.assertEqual(moved["x"], 300.0)
        self.assertEqual(moved["y"], 100.0)

    def test_can_place_part_at_collision(self):
        ok, msg = can_place_part_at(self.layout, 0, "A", 120.0, 20.0)
        self.assertFalse(ok)
        self.assertIn("kerf", msg.lower())

    def test_compute_position_grid_contains_both_states(self):
        rows = compute_position_grid(self.layout, 0, "A", 100.0)
        self.assertTrue(any(r["is_legal"] for r in rows))
        self.assertTrue(any(not r["is_legal"] for r in rows))


if __name__ == "__main__":
    unittest.main()
