import json
import base64
import io
import re
import zipfile
from datetime import datetime

import ezdxf

from nesting_engine import run_selco_nesting, run_smart_nesting
from panel_utils import normalize_panels


def build_nest_payload(nest_name, sheet_w, sheet_h, margin, kerf, panels, manual_layout=None, machine_type="Flat Bed"):
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
            "machine_type": str(machine_type),
        },
        "panels": normalized_panels,
        "packed_sheets": [],
    }

    if manual_layout and manual_layout.get("sheets"):
        payload["packed_sheets"] = manual_layout.get("sheets", [])
    else:
        if machine_type == "Selco":
            packer = run_selco_nesting(normalized_panels, sheet_w, sheet_h, margin, kerf)
        else:
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
    packed_sheets = payload.get("packed_sheets", [])
    manual_layout = None
    if packed_sheets and isinstance(packed_sheets, list) and "parts" in packed_sheets[0]:
        manual_layout = {
            "sheet_w": float(settings.get("sheet_w", 2440.0)),
            "sheet_h": float(settings.get("sheet_h", 1220.0)),
            "kerf": float(settings.get("kerf", 6.0)),
            "margin": float(settings.get("margin", 10.0)),
            "sheets": packed_sheets,
        }

    return {
        "sheet_w": float(settings.get("sheet_w", 2440.0)),
        "sheet_h": float(settings.get("sheet_h", 1220.0)),
        "kerf": float(settings.get("kerf", 6.0)),
        "margin": float(settings.get("margin", 10.0)),
        "panels": normalize_panels(payload.get("panels", [])),
        "nest_name": str(payload.get("nest_name", "Untitled")),
        "manual_layout": manual_layout,
        "machine_type": str(settings.get("machine_type", "Flat Bed")),
        "cix_preview": payload.get("cix_preview"),
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
            "machine_type": "Flat Bed",
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




def _parse_cix_macro_params(block_text):
    params = {}
    for param_name, param_value in re.findall(r'(?im)PARAM,\s*NAME\s*=\s*"?([A-Z0-9_]+)"?\s*,\s*VALUE\s*=\s*"?([^"\n\r]*)"?', block_text):
        params[param_name.upper()] = param_value.strip()
    return params


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _extract_cix_machining_preview(cix_text):
    macro_blocks = re.findall(r'(?is)BEGIN\s+MACRO\s*(.*?)\s*END\s+MACRO', cix_text)

    borings = []
    toolpath_segments = []
    current_point = None

    for block in macro_blocks:
        name_match = re.search(r'(?im)^\s*NAME\s*=\s*"?([A-Z0-9_]+)"?\s*$', block)
        if not name_match:
            continue
        macro_name = name_match.group(1).upper()
        params = _parse_cix_macro_params(block)

        if macro_name == 'START_POINT':
            current_point = (_safe_float(params.get('X')), _safe_float(params.get('Y')))
        elif macro_name == 'LINE_EP':
            end_point = (_safe_float(params.get('XE')), _safe_float(params.get('YE')))
            if current_point is not None:
                toolpath_segments.append({
                    'x1': float(current_point[0]),
                    'y1': float(current_point[1]),
                    'x2': float(end_point[0]),
                    'y2': float(end_point[1]),
                })
            current_point = end_point
        elif macro_name in {'ENDPATH', 'GEO'}:
            continue
        elif macro_name == 'BG':
            borings.append({
                'x': _safe_float(params.get('X')),
                'y': _safe_float(params.get('Y')),
                'depth': _safe_float(params.get('DP')),
                'tool': params.get('TNM', ''),
                'side': params.get('SIDE', ''),
            })

    return {
        'toolpath_segments': toolpath_segments,
        'borings': borings,
    }


_CIX_DIMENSION_PATTERN = re.compile(r'(?i)(LPX|LPY|LPZ|DX|DY)\s*=\s*"?([0-9]+(?:\.[0-9]+)?)"?')
_CIX_PARAM_PATTERN = re.compile(r'(?is)NAME\s*=\s*"?(LPX|LPY|LPZ|DX|DY)"?[^\n\r]*?VALUE\s*=\s*"?([0-9]+(?:\.[0-9]+)?)"?')
_CIX_SHEET_PATTERN = re.compile(r'(?i)(PAN=|LX=|LY=)')


def cix_to_payload(cix_bytes):
    cix_text = cix_bytes.decode("utf-8", errors="ignore")
    dimensions = {}
    for key, value in _CIX_DIMENSION_PATTERN.findall(cix_text):
        dimensions[key.upper()] = float(value)
    for key, value in _CIX_PARAM_PATTERN.findall(cix_text):
        dimensions[key.upper()] = float(value)

    width = dimensions.get("LPX", dimensions.get("DX"))
    length = dimensions.get("LPY", dimensions.get("DY"))
    if not width or not length:
        raise ValueError("Unable to find LPX/LPY (or DX/DY) dimensions in CIX file")

    material = "Loaded CIX"
    if _CIX_SHEET_PATTERN.search(cix_text):
        material = "CIX Sheet"

    preview = _extract_cix_machining_preview(cix_text)

    return {
        "version": 1,
        "nest_name": "Imported CIX Nest",
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "settings": {
            "sheet_w": 2440.0,
            "sheet_h": 1220.0,
            "margin": 0.0,
            "kerf": 0.0,
            "machine_type": "Flat Bed",
        },
        "panels": normalize_panels([
            {
                "Label": "Loaded CIX Part 1",
                "Width": float(width),
                "Length": float(length),
                "Qty": 1,
                "Grain?": False,
                "Material": material,
            }
        ]),
        "packed_sheets": [],
        "cix_preview": {
            "panel_width": float(width),
            "panel_length": float(length),
            "panel_thickness": _safe_float(dimensions.get("LPZ"), 0.0),
            "borings": preview["borings"],
            "toolpath_segments": preview["toolpath_segments"],
        },
    }


def nest_file_to_payload(file_name, file_bytes):
    ext = str(file_name or "").lower().rsplit(".", 1)[-1] if "." in str(file_name or "") else ""
    if ext == "cix":
        return cix_to_payload(file_bytes)
    return dxf_to_payload(file_bytes)


def _format_cix_value(value):
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _cix_macro(name, params):
    lines = ["BEGIN MACRO", f"	NAME={name}"]
    for key, value in params.items():
        lines.append(f"	PARAM,NAME={key},VALUE={_format_cix_value(value)}")
    lines.append("END MACRO")
    return "\n".join(lines)


def _transform_template_value(value, template_size, target_size):
    value_f = _safe_float(value)
    if template_size <= 0:
        return value_f
    return value_f * (target_size / template_size)


def _build_cix_program(panel_w, panel_h, panel_t, label, template_preview=None):
    template_preview = template_preview or {}
    template_w = _safe_float(template_preview.get("panel_width"), panel_w)
    template_h = _safe_float(template_preview.get("panel_length"), panel_h)

    program_lines = [
        "BEGIN ID CID3",
        "	REL=5.0",
        "END ID",
        "",
        "BEGIN MAINDATA",
        f"	LPX={_format_cix_value(panel_w)}",
        f"	LPY={_format_cix_value(panel_h)}",
        f"	LPZ={_format_cix_value(panel_t)}",
        '	ORLST="9"',
        "	SIMMETRY=0",
        "END MAINDATA",
        "",
        "BEGIN PUBLICVARS",
        "END PUBLICVARS",
        "",
    ]

    # Outer contour path (rectangle)
    program_lines.append(_cix_macro("GEO", {"LAY": "Layer 0", "ID": "G1001", "SIDE": 0, "CRN": "2", "RTY": 2}))
    program_lines.append("")
    program_lines.append(_cix_macro("START_POINT", {"LAY": "Layer 0", "X": 0, "Y": panel_h}))
    program_lines.append("")
    for idx, (xe, ye) in enumerate([(0, 0), (panel_w, 0), (panel_w, panel_h), (0, panel_h)]):
        program_lines.append(_cix_macro("LINE_EP", {"LAY": "Layer 0", "ID": 100 + idx, "XE": xe, "YE": ye, "ZS": 0, "ZE": 0, "FD": 0, "SP": 0, "MVT": 0}))
        program_lines.append("")
    program_lines.append(_cix_macro("ENDPATH", {}))
    program_lines.append("")

    # Apply template boring operations to this panel by size-relative mapping
    for i, boring in enumerate(template_preview.get("borings", []), start=1):
        x = _transform_template_value(boring.get("x", 0), template_w, panel_w)
        y = _transform_template_value(boring.get("y", 0), template_h, panel_h)
        depth = _safe_float(boring.get("depth", 0.0))
        tool = boring.get("tool") or "DRILL"
        program_lines.append(_cix_macro("BG", {
            "LAY": "Layer 1",
            "ID": f"P{i}",
            "SIDE": int(_safe_float(boring.get("side", 0))),
            "CRN": "1",
            "X": x,
            "Y": y,
            "Z": 0,
            "DP": depth,
            "TNM": tool,
            "CKA": 3,
            "OPT": 1,
        }))
        program_lines.append("")

    # Keep template path entities as an extra machining layer if present
    for i, seg in enumerate(template_preview.get("toolpath_segments", []), start=1):
        sx = _transform_template_value(seg.get("x1", 0), template_w, panel_w)
        sy = _transform_template_value(seg.get("y1", 0), template_h, panel_h)
        ex = _transform_template_value(seg.get("x2", 0), template_w, panel_w)
        ey = _transform_template_value(seg.get("y2", 0), template_h, panel_h)
        program_lines.append(_cix_macro("START_POINT", {"LAY": "Layer TP", "X": sx, "Y": sy}))
        program_lines.append("")
        program_lines.append(_cix_macro("LINE_EP", {"LAY": "Layer TP", "ID": 5000 + i, "XE": ex, "YE": ey, "ZS": 0, "ZE": 0, "FD": 0, "SP": 0, "MVT": 0}))
        program_lines.append("")

    program_lines.append(f"'LABEL={label}'")
    return "\n".join(program_lines).strip() + "\n"


def create_cix_zip(layout, template_preview=None):
    if not layout or not layout.get("sheets"):
        raise ValueError("No layout data available to export CIX")

    zip_buffer = io.BytesIO()
    thickness = _safe_float((template_preview or {}).get("panel_thickness"), 18.0)

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for sheet in layout.get("sheets", []):
            sheet_index = int(sheet.get("sheet_index", 0)) + 1
            for part_idx, part in enumerate(sheet.get("parts", []), start=1):
                part_w = _safe_float(part.get("w"), 0.0)
                part_h = _safe_float(part.get("h"), 0.0)
                if part_w <= 0 or part_h <= 0:
                    continue
                rid = str(part.get("rid") or f"Part_{part_idx}")
                safe_rid = re.sub(r'[^A-Za-z0-9._-]+', '_', rid).strip('_') or f"Part_{part_idx}"
                cix_text = _build_cix_program(part_w, part_h, thickness, rid, template_preview=template_preview)
                file_name = f"Sheet_{sheet_index}/{part_idx:03d}_{safe_rid}.cix"
                zip_file.writestr(file_name, cix_text)

    return zip_buffer.getvalue()
