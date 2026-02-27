import json
import base64
import io
import re
import ast
import operator
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


_CIX_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _eval_cix_numeric_expression(value):
    expression = str(value).strip()
    if not expression:
        raise ValueError("Empty expression")

    # Keep the evaluator strict: only simple numeric arithmetic is permitted.
    if not re.fullmatch(r"[0-9eE+\-*/().\s]+", expression):
        raise ValueError("Unsupported characters in expression")

    def _eval_node(node):
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Unsupported constant")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = _eval_node(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp) and type(node.op) in _CIX_ALLOWED_OPERATORS:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            return _CIX_ALLOWED_OPERATORS[type(node.op)](left, right)
        raise ValueError("Unsupported expression")

    tree = ast.parse(expression, mode="eval")
    return float(_eval_node(tree))


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        pass

    if isinstance(value, str):
        try:
            return _eval_cix_numeric_expression(value)
        except (ValueError, SyntaxError, ZeroDivisionError):
            pass

    return float(default)


def _extract_cix_machining_preview(cix_text):
    macro_blocks = re.findall(r'(?is)BEGIN\s+MACRO\s*(.*?)\s*END\s+MACRO', cix_text)

    borings = []
    toolpath_segments = []
    operations = []
    current_point = None
    current_geo_id = None
    current_geo_side = 0
    geo_anchor_points = {}
    geo_circles = {}

    for block in macro_blocks:
        name_match = re.search(r'(?im)^\s*NAME\s*=\s*"?([A-Z0-9_]+)"?\s*$', block)
        if not name_match:
            continue
        macro_name = name_match.group(1).upper()
        params = _parse_cix_macro_params(block)

        if macro_name == 'GEO':
            current_geo_id = params.get('ID')
            current_geo_side = int(_safe_float(params.get('SIDE', 0), 0))
        elif macro_name == 'START_POINT':
            current_point = (_safe_float(params.get('X')), _safe_float(params.get('Y')))
            if current_geo_id:
                geo_anchor_points[current_geo_id] = {
                    'x': float(current_point[0]),
                    'y': float(current_point[1]),
                    'side': current_geo_side,
                }
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
        elif macro_name == 'CIRCLE_CR':
            if current_geo_id:
                geo_circles[current_geo_id] = {
                    'xc': _safe_float(params.get('XC')),
                    'yc': _safe_float(params.get('YC')),
                    'r': _safe_float(params.get('R')),
                    'side': current_geo_side,
                }
        elif macro_name == 'ENDPATH':
            continue
        elif macro_name == 'BG':
            op = {
                'type': 'BG',
                'x': _safe_float(params.get('X')),
                'y': _safe_float(params.get('Y')),
                'depth': _safe_float(params.get('DP')),
                'tool': params.get('TNM', ''),
                'side': int(_safe_float(params.get('SIDE', 0), 0)),
            }
            borings.append({
                'x': op['x'],
                'y': op['y'],
                'depth': op['depth'],
                'tool': op['tool'],
                'side': op['side'],
            })
            operations.append(op)
        elif macro_name == 'B_GEO':
            gid = params.get('GID', '')
            anchor = geo_anchor_points.get(gid)
            if not anchor:
                continue

            op = {
                'type': 'B_GEO',
                'x': anchor['x'],
                'y': anchor['y'],
                'depth': _safe_float(params.get('DP')),
                'tool': params.get('TNM', ''),
                'side': int(_safe_float(params.get('SIDE', anchor.get('side', 0)), 0)),
            }
            borings.append({
                'x': op['x'],
                'y': op['y'],
                'depth': op['depth'],
                'tool': op['tool'],
                'side': op['side'],
            })
            operations.append(op)
        elif macro_name == 'ROUTG':
            gid = params.get('GID', '')
            circle = geo_circles.get(gid)
            if not circle:
                continue
            operations.append({
                'type': 'ROUTG_CIRCLE',
                'xc': circle['xc'],
                'yc': circle['yc'],
                'r': circle['r'],
                'depth': _safe_float(params.get('DP')),
                'tool': params.get('TNM', ''),
                'side': int(_safe_float(params.get('SIDE', circle.get('side', 0)), 0)),
            })

    return {
        'toolpath_segments': toolpath_segments,
        'borings': borings,
        'operations': operations,
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
            "operations": preview.get("operations", []),
        },
    }


def nest_file_to_payload(file_name, file_bytes):
    ext = str(file_name or "").lower().rsplit(".", 1)[-1] if "." in str(file_name or "") else ""
    if ext == "cix":
        return cix_to_payload(file_bytes)
    return dxf_to_payload(file_bytes)




def _sanitize_cix_name(value, fallback="PART"):
    raw = str(value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    return cleaned[:40] or fallback

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


def _map_template_point_to_sheet(x, y, part, template_w, template_h, coord_mode="absolute"):
    part_w = _safe_float(part.get("w"), 0.0)
    part_h = _safe_float(part.get("h"), 0.0)
    part_x = _safe_float(part.get("x"), 0.0)
    part_y = _safe_float(part.get("y"), 0.0)

    coord_mode = str(coord_mode or "absolute").lower()

    if coord_mode == "normalized":
        sx = _transform_template_value(x, 1.0, part_w)
        sy = _transform_template_value(y, 1.0, part_h)
        if part.get("rotated"):
            return part_x + (part_w - sy), part_y + sx
        return part_x + sx, part_y + sy

    # Absolute tooling coordinates: keep tool geometry true to panel dimensions.
    point_x = _safe_float(x)
    point_y = _safe_float(y)

    rotated_flag = bool(part.get("rotated"))
    swapped_dims = (
        template_w > 0 and template_h > 0 and
        abs(part_w - template_h) <= 0.01 and
        abs(part_h - template_w) <= 0.01
    )

    if rotated_flag or swapped_dims:
        # 90° clockwise transform from template coordinates into sheet coordinates.
        return part_x + (part_w - point_y), part_y + point_x

    if template_w > 0 and template_h > 0 and (
        abs(part_w - template_w) > 0.01 or abs(part_h - template_h) > 0.01
    ):
        # Fallback for non-normalized tooling where dimensions don't match exactly.
        sx = _transform_template_value(point_x, template_w, part_w)
        sy = _transform_template_value(point_y, template_h, part_h)
        return part_x + sx, part_y + sy

    return part_x + point_x, part_y + point_y



def _canonical_part_label(label):
    value = str(label or "").strip()
    # UI can append grouping suffixes like "(G)" to repeated labels.
    value = re.sub(r"\s*\([^)]+\)\s*$", "", value).strip()
    return value

def _get_part_tooling_preview(part, template_preview, panel_tooling_by_label):
    label = str(part.get("rid") or "")
    tooling = panel_tooling_by_label.get(label) if panel_tooling_by_label else None
    if isinstance(tooling, dict):
        return tooling

    canonical_label = _canonical_part_label(label)
    if panel_tooling_by_label and canonical_label:
        tooling = panel_tooling_by_label.get(canonical_label)
        if isinstance(tooling, dict):
            return tooling

    return template_preview or {}


def _get_template_sizes_for_part(preview, part_w, part_h):
    coord_mode = str(preview.get("coord_mode", "absolute")).lower()
    if coord_mode == "normalized":
        return 1.0, 1.0
    template_w = _safe_float(preview.get("panel_width"), part_w)
    template_h = _safe_float(preview.get("panel_length"), part_h)
    return template_w, template_h


def _get_routing_tool_name(preview):
    routing = preview.get("routing") if isinstance(preview, dict) else None
    if isinstance(routing, dict):
        tool_name = routing.get("tool")
        if tool_name:
            return str(tool_name)
    return "6MM"


def _append_routing_macros(program_lines, part_idx, part_name, geo_id, tool_name):
    program_lines.append(_cix_macro("WFL", {
        "ID": 9000 + part_idx,
        "X": 0,
        "Y": 0,
        "Z": 0,
        "AZ": 90,
        "AR": 0,
        "UCS": 1,
        "RV": 0,
        "FRC": 1,
    }))
    program_lines.append("")
    program_lines.append(_cix_macro("ROUTG", {
        "LAY": f"Route_{part_name}",
        "ID": f"R{part_idx}",
        "GID": geo_id,
        "Z": 0,
        "DP": 0,
        "THR": 1,
        "CRC": 2,
        "CKA": 3,
        "OPT": 1,
        "RSP": 18000,
        "WSP": 10000,
        "DSP": 5000,
        "TIN": 0,
        "CIN": 0,
        "TOU": 0,
        "COU": 0,
        "TNM": tool_name,
        "TOS": 1,
    }))
    program_lines.append("")


def build_sheet_boring_points(parts, panel_tooling_by_label=None, template_preview=None):
    panel_tooling_by_label = panel_tooling_by_label or {}
    template_preview = template_preview or {}
    points = []

    for part in parts or []:
        part_w = _safe_float(part.get("w"), 0.0)
        part_h = _safe_float(part.get("h"), 0.0)
        if part_w <= 0 or part_h <= 0:
            continue

        active_preview = _get_part_tooling_preview(part, template_preview, panel_tooling_by_label)
        template_w, template_h = _get_template_sizes_for_part(active_preview, part_w, part_h)
        coord_mode = str(active_preview.get("coord_mode", "absolute")).lower()

        for boring in active_preview.get("borings", []):
            bx, by = _map_template_point_to_sheet(
                boring.get("x", 0),
                boring.get("y", 0),
                part,
                template_w,
                template_h,
                coord_mode=coord_mode,
            )
            points.append({
                "x": bx,
                "y": by,
                "tool": boring.get("tool", ""),
                "label": str(part.get("rid") or "Part"),
            })

    return points


def _build_sheet_cix_program(sheet_w, sheet_h, panel_t, parts, template_preview=None):
    template_preview = template_preview or {}

    program_lines = [
        "BEGIN ID CID3",
        "	REL=5.0",
        "END ID",
        "",
        "BEGIN MAINDATA",
        f"	LPX={_format_cix_value(sheet_w)}",
        f"	LPY={_format_cix_value(sheet_h)}",
        f"	LPZ={_format_cix_value(panel_t)}",
        '	ORLST="9"',
        "	SIMMETRY=0",
        "END MAINDATA",
        "",
        "BEGIN PUBLICVARS",
        "END PUBLICVARS",
        "",
    ]

    for part_idx, part in enumerate(parts, start=1):
        part_w = _safe_float(part.get("w"), 0.0)
        part_h = _safe_float(part.get("h"), 0.0)
        if part_w <= 0 or part_h <= 0:
            continue

        part_x = _safe_float(part.get("x"), 0.0)
        part_y = _safe_float(part.get("y"), 0.0)
        part_label = str(part.get("rid") or f"Part_{part_idx}")
        part_name = _sanitize_cix_name(part_label, fallback=f"PART_{part_idx}")
        geo_id = f"G{part_name}"

        program_lines.append(_cix_macro("GEO", {"LAY": f"Part_{part_name}", "ID": geo_id, "SIDE": 0, "CRN": "2", "RTY": 2}))
        program_lines.append("")
        program_lines.append(_cix_macro("START_POINT", {"LAY": "Layer 0", "X": part_x, "Y": part_y + part_h}))
        program_lines.append("")
        for seg_idx, (xe, ye) in enumerate([
            (part_x, part_y),
            (part_x + part_w, part_y),
            (part_x + part_w, part_y + part_h),
            (part_x, part_y + part_h),
        ]):
            program_lines.append(_cix_macro("LINE_EP", {
                "LAY": "Layer 0",
                "ID": 1000 * part_idx + seg_idx,
                "XE": xe,
                "YE": ye,
                "ZS": 0,
                "ZE": 0,
                "FD": 0,
                "SP": 0,
                "MVT": 0,
            }))
            program_lines.append("")
        program_lines.append(_cix_macro("ENDPATH", {}))
        program_lines.append("")

        _append_routing_macros(program_lines, part_idx, part_name, geo_id, _get_routing_tool_name(template_preview))
        program_lines.append(f"'PART_LABEL={part_label}'")
        program_lines.append("")

    return "\n".join(program_lines).strip() + "\n"


def create_cix_zip(layout, template_preview=None):
    if not layout or not layout.get("sheets"):
        raise ValueError("No layout data available to export CIX")

    zip_buffer = io.BytesIO()
    thickness = _safe_float((template_preview or {}).get("panel_thickness"), 18.0)
    sheet_w = _safe_float(layout.get("sheet_w"), 2440.0)
    sheet_h = _safe_float(layout.get("sheet_h"), 1220.0)

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for sheet in layout.get("sheets", []):
            sheet_index = int(sheet.get("sheet_index", 0)) + 1
            parts = sheet.get("parts", [])
            if not parts:
                continue
            cix_text = _build_sheet_cix_program(sheet_w, sheet_h, thickness, parts, template_preview=template_preview)
            zip_file.writestr(f"Sheet_{sheet_index}.cix", cix_text)

    return zip_buffer.getvalue()
