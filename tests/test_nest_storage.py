import unittest
import io
import zipfile

import ezdxf

from nest_storage import build_nest_payload, create_cix_zip, parse_nest_payload, payload_to_dxf, dxf_to_payload, cix_to_payload, nest_file_to_payload


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
        self.assertEqual(parsed["machine_type"], "Flat Bed")

    def test_selco_machine_type_round_trip(self):
        payload = build_nest_payload(
            "Selco Job",
            3050,
            1220,
            0,
            0,
            [{"Label": "Panel", "Width": 600, "Length": 800, "Qty": 2, "Grain?": False, "Material": "Ply"}],
            machine_type="Selco",
        )

        self.assertEqual(payload["settings"]["machine_type"], "Selco")

        loaded_payload = dxf_to_payload(payload_to_dxf(payload))
        parsed = parse_nest_payload(loaded_payload)

        self.assertEqual(parsed["machine_type"], "Selco")


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


    def test_manual_layout_round_trip(self):
        manual_layout = {
            "sheet_w": 2440.0,
            "sheet_h": 1220.0,
            "margin": 10.0,
            "kerf": 6.0,
            "sheets": [
                {
                    "sheet_index": 0,
                    "parts": [
                        {
                            "id": "S1-P1",
                            "rid": "Panel A",
                            "x": 100.0,
                            "y": 120.0,
                            "w": 300.0,
                            "h": 400.0,
                            "rotated": False,
                        }
                    ],
                }
            ],
        }
        payload = build_nest_payload(
            "Manual Layout",
            2440,
            1220,
            10,
            6,
            [{"Label": "Panel A", "Width": 300, "Length": 400, "Qty": 1, "Grain?": False, "Material": "Ply"}],
            manual_layout=manual_layout,
        )

        loaded_payload = dxf_to_payload(payload_to_dxf(payload))
        parsed = parse_nest_payload(loaded_payload)

        self.assertIsNotNone(parsed["manual_layout"])
        self.assertEqual(parsed["manual_layout"]["sheets"][0]["parts"][0]["x"], 100.0)
        self.assertEqual(parsed["manual_layout"]["sheets"][0]["parts"][0]["y"], 120.0)



    def test_cix_import_loads_panel_dimensions(self):
        cix_bytes = b"BEGIN MACRO\nPARAM,NAME=LPX,VALUE=\"762\"\nPARAM,NAME=LPY,VALUE=\"508\"\nEND MACRO\n"

        loaded_payload = cix_to_payload(cix_bytes)
        parsed = parse_nest_payload(loaded_payload)

        self.assertEqual(len(parsed["panels"]), 1)
        self.assertEqual(parsed["panels"][0]["Width"], 762.0)
        self.assertEqual(parsed["panels"][0]["Length"], 508.0)



    def test_cix_import_extracts_borings_and_toolpaths_for_preview(self):
        cix_bytes = b"""BEGIN MAINDATA
LPX=800
LPY=500
LPZ=18
END MAINDATA

BEGIN MACRO
NAME=START_POINT
PARAM,NAME=X,VALUE=0
PARAM,NAME=Y,VALUE=500
END MACRO

BEGIN MACRO
NAME=LINE_EP
PARAM,NAME=XE,VALUE=800
PARAM,NAME=YE,VALUE=500
END MACRO

BEGIN MACRO
NAME=BG
PARAM,NAME=X,VALUE=50
PARAM,NAME=Y,VALUE=50
PARAM,NAME=DP,VALUE=14
PARAM,NAME=TNM,VALUE="5MMDRILL"
END MACRO
"""

        payload = cix_to_payload(cix_bytes)
        parsed = parse_nest_payload(payload)

        self.assertIsNotNone(parsed["cix_preview"])
        self.assertEqual(parsed["cix_preview"]["panel_width"], 800.0)
        self.assertEqual(parsed["cix_preview"]["panel_length"], 500.0)
        self.assertEqual(parsed["cix_preview"]["panel_thickness"], 18.0)
        self.assertEqual(len(parsed["cix_preview"]["toolpath_segments"]), 1)
        self.assertEqual(len(parsed["cix_preview"]["borings"]), 1)
        self.assertEqual(parsed["cix_preview"]["borings"][0]["tool"], "5MMDRILL")

    def test_nest_file_to_payload_routes_cix_by_extension(self):
        cix_bytes = b"LPX=600\nLPY=300\n"

        loaded_payload = nest_file_to_payload("part.cix", cix_bytes)
        parsed = parse_nest_payload(loaded_payload)

        self.assertEqual(parsed["panels"][0]["Width"], 600.0)
        self.assertEqual(parsed["panels"][0]["Length"], 300.0)



    def test_create_cix_zip_exports_whole_sheet_program_with_nested_parts(self):
        layout = {
            "sheet_w": 2440.0,
            "sheet_h": 1220.0,
            "sheets": [
                {
                    "sheet_index": 0,
                    "parts": [
                        {"rid": "Door A", "x": 100.0, "y": 200.0, "w": 800.0, "h": 500.0, "rotated": False},
                        {"rid": "Door B", "x": 1000.0, "y": 300.0, "w": 400.0, "h": 250.0, "rotated": False},
                    ],
                }
            ]
        }
        template_preview = {
            "panel_width": 800.0,
            "panel_length": 500.0,
            "panel_thickness": 18.0,
            "borings": [{"x": 50.0, "y": 50.0, "depth": 14.0, "tool": "5MMDRILL", "side": 0}],
            "toolpath_segments": [{"x1": 0.0, "y1": 500.0, "x2": 800.0, "y2": 500.0}],
        }

        cix_zip = create_cix_zip(layout, template_preview)

        with zipfile.ZipFile(io.BytesIO(cix_zip), "r") as zf:
            names = sorted(zf.namelist())
            self.assertEqual(names, ["Sheet_1.cix"])
            sheet_program = zf.read("Sheet_1.cix").decode("utf-8")

        self.assertIn("LPX=2440", sheet_program)
        self.assertIn("LPY=1220", sheet_program)

        # Both parts are represented in one sheet program.
        self.assertIn("'PART_LABEL=Door A'", sheet_program)
        self.assertIn("'PART_LABEL=Door B'", sheet_program)

        # Part names are embedded in machining macros for CAD visibility.
        self.assertIn('PARAM,NAME=LAY,VALUE="Part_Door_A"', sheet_program)
        self.assertIn('PARAM,NAME=ID,VALUE="Door_A"', sheet_program)
        self.assertIn('PARAM,NAME=LAY,VALUE="Part_Door_B"', sheet_program)
        self.assertIn('PARAM,NAME=ID,VALUE="Door_B"', sheet_program)

        # First part boring at (100,200) + (50,50)
        self.assertIn("PARAM,NAME=X,VALUE=150", sheet_program)
        self.assertIn("PARAM,NAME=Y,VALUE=250", sheet_program)

        # Second part boring scales 50,50 on 800x500 -> 25,25 then offset (1000,300)
        self.assertIn("PARAM,NAME=X,VALUE=1025", sheet_program)
        self.assertIn("PARAM,NAME=Y,VALUE=325", sheet_program)
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
