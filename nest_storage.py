import json
import base64
import io
from datetime import datetime

import ezdxf

from nesting_engine import run_smart_nesting
from panel_utils import normalize_panels


def build_nest_payload(nest_name, sheet_w, sheet_h, margin, kerf, panels):
    normalized_panels = normalize_panels(panels)
    payload = {
        "version": 1,
        "nest_name": nest_name,
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "settings": {
            "sheet_w": float(sheet_w),
            "sheet_h": float(sheet_h),
            "margin": float(margin),
            "kerf": float(kerf),
        },
        "panels": normalized_panels,
        "packed_sheets": [],
    }

    packer = run_smart_nesting(normalized_panels, sheet_w, sheet_h, margin, kerf)
    if packer:
        for sheet_index, bin in enumerate(packer):
            rects = []
            for rect in bin:
                rects.append({
                    "x": float(rect.x),
                    "y": float(rect.y),
                    "width": float(rect.width),
                    "height": float(rect.height),
                    "rid": str(rect.rid) if rect.rid else "Part",
                })
            payload["packed_sheets"].append({
                "sheet_index": sheet_index,
                "rects": rects,
            })
    return payload


def parse_nest_payload(payload):
    settings = payload.get("settings", {})
    return {
        "sheet_w": float(settings.get("sheet_w", 2440.0)),
        "sheet_h": float(settings.get("sheet_h", 1220.0)),
        "kerf": float(settings.get("kerf", 6.0)),
        "margin": float(settings.get("margin", 10.0)),
        "panels": normalize_panels(payload.get("panels", [])),
        "nest_name": str(payload.get("nest_name", "Untitled")),
    }


def payload_to_json(payload):
    return json.dumps(payload, indent=2)


_DXF_MARKER_BEGIN = "CNC_NESTER_PAYLOAD_BASE64_BEGIN"
_DXF_MARKER_END = "CNC_NESTER_PAYLOAD_BASE64_END"


def payload_to_dxf(payload):
    payload_bytes = payload_to_json(payload).encode("utf-8")
    encoded_payload = base64.b64encode(payload_bytes).decode("ascii")
    chunks = [encoded_payload[i:i + 250] for i in range(0, len(encoded_payload), 250)]

    dxf_lines = [
        "0", "SECTION",
        "2", "HEADER",
        "999", _DXF_MARKER_BEGIN,
    ]
    for chunk in chunks:
        dxf_lines.extend(["999", chunk])
    dxf_lines.extend([
        "999", _DXF_MARKER_END,
        "0", "ENDSEC",
        "0", "EOF",
    ])
    return ("\n".join(dxf_lines) + "\n").encode("utf-8")




def _polyline_bbox(points):
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _payload_from_dxf_geometry(dxf_bytes):
    dxf_text = dxf_bytes.decode("utf-8", errors="ignore")
    doc = ezdxf.read(io.StringIO(dxf_text))
    msp = doc.modelspace()

    sheet_w = 2440.0
    sheet_h = 1220.0
    panels = []

    for entity in msp.query("LWPOLYLINE"):
        layer = (entity.dxf.layer or "").upper()
        points = list(entity.get_points("xy"))
        if len(points) < 4:
            continue

        min_x, min_y, max_x, max_y = _polyline_bbox(points)
        width = max_x - min_x
        height = max_y - min_y
        if width <= 0 or height <= 0:
            continue

        if layer == "SHEET_BOUNDARY":
            sheet_w = width
            sheet_h = height
        elif layer == "CUT_LINES":
            panels.append({
                "Label": f"Loaded Part {len(panels) + 1}",
                "Width": width,
                "Length": height,
                "Qty": 1,
                "Grain?": False,
                "Material": "Loaded DXF",
            })

    if not panels:
        raise ValueError("No CNC Nester payload metadata found in DXF")

    return {
        "version": 1,
        "nest_name": "Imported DXF Nest",
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "settings": {
            "sheet_w": float(sheet_w),
            "sheet_h": float(sheet_h),
            "margin": 0.0,
            "kerf": 0.0,
        },
        "panels": normalize_panels(panels),
        "packed_sheets": [],
    }

def dxf_to_payload(dxf_bytes):
    lines = dxf_bytes.decode("utf-8").splitlines()
    comments = []
    for i in range(0, len(lines) - 1, 2):
        if lines[i].strip() == "999":
            comments.append(lines[i + 1].strip())

    if _DXF_MARKER_BEGIN not in comments or _DXF_MARKER_END not in comments:
        return _payload_from_dxf_geometry(dxf_bytes)

    start = comments.index(_DXF_MARKER_BEGIN) + 1
    end = comments.index(_DXF_MARKER_END)
    encoded_payload = "".join(comments[start:end])
    payload_json = base64.b64decode(encoded_payload.encode("ascii")).decode("utf-8")
    return json.loads(payload_json)
