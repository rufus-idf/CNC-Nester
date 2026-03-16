from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def extract_spreadsheet_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if match:
        return match.group(1)

    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", text):
        return text

    return ""


def _rect_vertices(offcut: dict[str, Any]) -> list[list[float]]:
    x = round(_safe_float(offcut.get("x"), 0.0), 2)
    y = round(_safe_float(offcut.get("y"), 0.0), 2)
    w = round(_safe_float(offcut.get("width"), 0.0), 2)
    h = round(_safe_float(offcut.get("height"), 0.0), 2)

    return [
        [x, y],
        [round(x + w, 2), y],
        [round(x + w, 2), round(y + h, 2)],
        [x, round(y + h, 2)],
    ]


def _vertices_bbox(vertices: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [float(v[0]) for v in vertices]
    ys = [float(v[1]) for v in vertices]
    min_x = min(xs)
    min_y = min(ys)
    max_x = max(xs)
    max_y = max(ys)
    return min_x, min_y, max_x - min_x, max_y - min_y


def _svg_path_from_vertices(vertices: list[list[float]]) -> str:
    if not vertices:
        return ""
    segments = [f"M{vertices[0][0]} {vertices[0][1]}"]
    for point in vertices[1:]:
        segments.append(f"L{point[0]} {point[1]}")
    segments.append("Z")
    return " ".join(segments)


def build_offcut_stock_rows(
    layout: dict[str, Any],
    sheet: dict[str, Any],
    reusable_offcuts: list[dict[str, Any]],
    *,
    material: str = "",
    thickness_mm: Any = "",
    location: str = "",
    sheet_origin_job: str = "",
    captured_at_utc: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    timestamp = captured_at_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    stamp = timestamp.replace("-", "").replace(":", "").replace("T", "").replace("Z", "")
    sheet_idx = int(sheet.get("sheet_index", 0))

    inventory_rows: list[dict[str, Any]] = []
    shape_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    preview_rows: list[dict[str, Any]] = []

    for idx, offcut in enumerate(reusable_offcuts, start=1):
        offcut_id = f"OC-{stamp}-S{sheet_idx + 1:02d}-{idx:03d}"
        shape_ref = f"SH-{stamp}-S{sheet_idx + 1:02d}-{idx:03d}"
        preview_ref = f"PV-{stamp}-S{sheet_idx + 1:02d}-{idx:03d}"
        event_id = f"EV-{stamp}-S{sheet_idx + 1:02d}-{idx:03d}"

        shape_type = str(offcut.get("shape_type", "RECT") or "RECT").upper()
        raw_vertices = offcut.get("vertices")
        if isinstance(raw_vertices, list) and raw_vertices:
            vertices = [[round(_safe_float(v[0]), 2), round(_safe_float(v[1]), 2)] for v in raw_vertices if isinstance(v, (list, tuple)) and len(v) >= 2]
        else:
            vertices = _rect_vertices(offcut)

        min_x, min_y, width, height = _vertices_bbox(vertices)
        width = round(width, 2)
        height = round(height, 2)
        area = round(_safe_float(offcut.get("area"), width * height), 2)
        svg_path = _svg_path_from_vertices(vertices)

        inventory_rows.append({
            "offcut_id": offcut_id,
            "status": "IN_STOCK",
            "material": material,
            "thickness_mm": thickness_mm,
            "grade": "",
            "sheet_origin_job": sheet_origin_job,
            "sheet_origin_index": sheet_idx,
            "captured_at_utc": timestamp,
            "shape_type": shape_type,
            "area_mm2": area,
            "bbox_w_mm": width,
            "bbox_h_mm": height,
            "min_internal_width_mm": min(width, height),
            "usable_score": "",
            "location": location,
            "preview_ref": preview_ref,
            "shape_ref": shape_ref,
            "notes": "",
        })

        shape_rows.append({
            "shape_ref": shape_ref,
            "offcut_id": offcut_id,
            "coord_unit": "mm",
            "bbox_x_mm": round(_safe_float(offcut.get("x"), min_x), 2),
            "bbox_y_mm": round(_safe_float(offcut.get("y"), min_y), 2),
            "vertices_json": json.dumps(vertices),
            "holes_json": "[]",
            "version": 1,
        })

        event_rows.append({
            "event_id": event_id,
            "offcut_id": offcut_id,
            "event_type": "CREATED",
            "event_at_utc": timestamp,
            "job_id": sheet_origin_job,
            "user": "app",
            "payload_json": "{}",
        })

        preview_rows.append({
            "preview_ref": preview_ref,
            "offcut_id": offcut_id,
            "svg_path_data": svg_path,
            "scale_hint": "1:1 mm",
            "updated_at_utc": timestamp,
        })

    return {
        "offcut_inventory": inventory_rows,
        "offcut_shapes": shape_rows,
        "offcut_events": event_rows,
        "offcut_previews": preview_rows,
    }


def normalize_spreadsheet_reference(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    if text.startswith("https://docs.google.com/spreadsheets/"):
        return text

    spreadsheet_id = extract_spreadsheet_id(text)
    if spreadsheet_id:
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    return ""



def parse_vertices_json(value: Any) -> list[list[float]]:
    if value is None:
        return []

    if isinstance(value, list):
        raw_points = value
    else:
        text = str(value).strip()
        if not text:
            return []
        try:
            raw_points = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    points: list[list[float]] = []
    for point in raw_points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            points.append([round(float(point[0]), 2), round(float(point[1]), 2)])
        except (TypeError, ValueError):
            continue
    return points
