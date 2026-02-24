import unittest

from nesting_engine import run_selco_nesting, run_smart_nesting


class NestingEngineTests(unittest.TestCase):
    def test_can_pack_reported_ply_bed_case_on_one_sheet(self):
        panels = [
            {"Label": "Hinge Plates", "Width": 140, "Length": 1078, "Qty": 2, "Grain?": False, "Material": "Chalet Oak Ply"},
            {"Label": "Headboard", "Width": 800, "Length": 1201, "Qty": 1, "Grain?": False, "Material": "Chalet Oak Ply"},
            {"Label": "Bed Sides", "Width": 390, "Length": 1920, "Qty": 2, "Grain?": False, "Material": "Chalet Oak Ply"},
            {"Label": "Side Battens", "Width": 50, "Length": 745, "Qty": 4, "Grain?": False, "Material": "Chalet Oak Ply"},
            {"Label": "Footboard", "Width": 390, "Length": 1162, "Qty": 1, "Grain?": False, "Material": "Chalet Oak Ply"},
        ]

        packer = run_smart_nesting(panels, sheet_w=3050, sheet_h=1220, margin=0, kerf=0)

        self.assertIsNotNone(packer)
        self.assertEqual(len(packer.rect_list()), 10)
        self.assertEqual(len(packer), 1)


    def test_selco_mode_can_pack_simple_case(self):
        panels = [
            {"Label": "Panel A", "Width": 500, "Length": 700, "Qty": 2, "Grain?": False, "Material": "MDF"},
            {"Label": "Panel B", "Width": 300, "Length": 800, "Qty": 2, "Grain?": True, "Material": "MDF"},
        ]

        packer = run_selco_nesting(panels, sheet_w=2440, sheet_h=1220, margin=10, kerf=6)

        self.assertIsNotNone(packer)
        self.assertEqual(len(packer.rect_list()), 4)

if __name__ == "__main__":
    unittest.main()
