import unittest
import io

import ezdxf

from nest_storage import build_nest_payload, parse_nest_payload, payload_to_dxf, dxf_to_payload


class NestStorageTests(unittest.TestCase):
    def test_build_and_parse_round_trip(self):
        panels = [
            {"Label": "Headboard", "Width": 800, "Length": 1201, "Qty": 1, "Grain?": False, "Material": "Ply"},
            {"Label": "Bed Side", "Width": 390, "Length": 1920, "Qty": 2, "Grain?": True, "Material": "Ply"},
        ]

        payload = build_nest_payload("Bed 1", 3050, 1220, 0, 0, panels)
        parsed = parse_nest_payload(payload)

        self.assertEqual(parsed["nest_name"], "Bed 1")
        self.assertEqual(parsed["sheet_w"], 3050.0)
        self.assertEqual(parsed["sheet_h"], 1220.0)
        self.assertEqual(parsed["kerf"], 0.0)
        self.assertEqual(parsed["margin"], 0.0)
        self.assertEqual(len(parsed["panels"]), 2)
        self.assertIn("packed_sheets", payload)

    def test_payload_to_dxf_and_back_round_trip(self):
        payload = build_nest_payload(
            "Kitchen Run",
            2800,
            2070,
            10,
            6,
            [{"Label": "Door", "Width": 500, "Length": 700, "Qty": 4, "Grain?": False, "Material": "MDF"}],
        )

        dxf_bytes = payload_to_dxf(payload)
        loaded_payload = dxf_to_payload(dxf_bytes)

        self.assertEqual(loaded_payload["nest_name"], "Kitchen Run")
        self.assertEqual(loaded_payload["settings"]["sheet_w"], 2800.0)
        self.assertEqual(len(loaded_payload["panels"]), 1)

    def test_dxf_without_payload_raises_error(self):
        dxf_bytes = b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n"

        with self.assertRaises(ValueError):
            dxf_to_payload(dxf_bytes)

    def test_dxf_geometry_fallback_loads_panels(self):
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (3050, 0), (3050, 1220), (0, 1220), (0, 0)], dxfattribs={"layer": "SHEET_BOUNDARY"})
        msp.add_lwpolyline([(10, 10), (510, 10), (510, 710), (10, 710), (10, 10)], dxfattribs={"layer": "CUT_LINES"})

        out = io.StringIO()
        doc.write(out)
        dxf_bytes = out.getvalue().encode("utf-8")

        loaded_payload = dxf_to_payload(dxf_bytes)
        parsed = parse_nest_payload(loaded_payload)

        self.assertEqual(parsed["sheet_w"], 3050.0)
        self.assertEqual(parsed["sheet_h"], 1220.0)
        self.assertEqual(len(parsed["panels"]), 1)
        self.assertEqual(parsed["panels"][0]["Width"], 500.0)
        self.assertEqual(parsed["panels"][0]["Length"], 700.0)


if __name__ == "__main__":
    unittest.main()
