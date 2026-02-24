import unittest

from manual_layout import can_place, move_part, rotate_part_90


class ManualLayoutTests(unittest.TestCase):
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

    def test_move_rejects_kerf_violation(self):
        updated, ok, _ = move_part(self.layout, 0, "A", 75, 0)
        self.assertFalse(ok)
        self.assertEqual(updated, self.layout)

    def test_rotate_rejects_margin_violation(self):
        # Put a tall part near top so rotation would exceed bounds
        self.layout["sheets"][0]["parts"][0].update({"x": 20.0, "y": 460.0, "w": 40.0, "h": 50.0})
        updated, ok, _ = rotate_part_90(self.layout, 0, "A")
        self.assertFalse(ok)
        self.assertEqual(updated, self.layout)

    def test_can_place_accepts_valid_gap(self):
        rect = {"x": 130.0, "y": 20.0, "w": 50.0, "h": 50.0}
        ok, _ = can_place(rect, self.layout["sheets"][0]["parts"], "A", 1000, 500, 10, 7)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
