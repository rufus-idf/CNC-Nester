from __future__ import annotations


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _intersects(a, b):
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


def _rect_contained(inner, outer, tol=1e-6):
    return (
        inner["x"] >= outer["x"] - tol
        and inner["y"] >= outer["y"] - tol
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + tol
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + tol
    )


def _subtract_rect(container, cut):
    if not _intersects(container, cut):
        return [container]

    cx, cy, cw, ch = container["x"], container["y"], container["w"], container["h"]
    kx, ky, kw, kh = cut["x"], cut["y"], cut["w"], cut["h"]

    ix1 = max(cx, kx)
    iy1 = max(cy, ky)
    ix2 = min(cx + cw, kx + kw)
    iy2 = min(cy + ch, ky + kh)

    if ix2 <= ix1 or iy2 <= iy1:
        return [container]

    pieces = []

    if iy2 < cy + ch:
        pieces.append({"x": cx, "y": iy2, "w": cw, "h": (cy + ch) - iy2})
    if iy1 > cy:
        pieces.append({"x": cx, "y": cy, "w": cw, "h": iy1 - cy})
    if ix1 > cx:
        pieces.append({"x": cx, "y": iy1, "w": ix1 - cx, "h": iy2 - iy1})
    if ix2 < cx + cw:
        pieces.append({"x": ix2, "y": iy1, "w": (cx + cw) - ix2, "h": iy2 - iy1})

    return [p for p in pieces if p["w"] > 1e-6 and p["h"] > 1e-6]


def _prune_contained(rects):
    kept = []
    for i, rect in enumerate(rects):
        contained = False
        for j, other in enumerate(rects):
            if i == j:
                continue
            if _rect_contained(rect, other):
                contained = True
                break
        if not contained:
            kept.append(rect)
    return kept


def calculate_sheet_offcuts(layout, sheet, min_width=120.0, min_height=120.0, min_area=25000.0):
    margin = _safe_float(layout.get("margin"), 0.0)
    sheet_w = _safe_float(layout.get("sheet_w"), 0.0)
    sheet_h = _safe_float(layout.get("sheet_h"), 0.0)

    usable = {
        "x": margin,
        "y": margin,
        "w": max(0.0, sheet_w - (2.0 * margin)),
        "h": max(0.0, sheet_h - (2.0 * margin)),
    }
    interior_area = usable["w"] * usable["h"]

    parts = []
    for part in sheet.get("parts", []):
        px = max(usable["x"], _safe_float(part.get("x"), 0.0))
        py = max(usable["y"], _safe_float(part.get("y"), 0.0))
        pw = _safe_float(part.get("w"), 0.0)
        ph = _safe_float(part.get("h"), 0.0)
        px2 = min(usable["x"] + usable["w"], px + pw)
        py2 = min(usable["y"] + usable["h"], py + ph)
        cw = max(0.0, px2 - px)
        ch = max(0.0, py2 - py)
        if cw > 0 and ch > 0:
            parts.append({"x": px, "y": py, "w": cw, "h": ch})

    parts.sort(key=lambda r: (r["y"], r["x"]))

    free_rects = [usable]
    for part in parts:
        next_rects = []
        for free_rect in free_rects:
            next_rects.extend(_subtract_rect(free_rect, part))
        free_rects = _prune_contained(next_rects)

    used_area = sum(p["w"] * p["h"] for p in parts)
    waste_area = sum(r["w"] * r["h"] for r in free_rects)

    reusable = [
        {
            "x": round(r["x"], 2),
            "y": round(r["y"], 2),
            "width": round(r["w"], 2),
            "height": round(r["h"], 2),
            "area": round(r["w"] * r["h"], 2),
        }
        for r in free_rects
        if r["w"] >= min_width and r["h"] >= min_height and (r["w"] * r["h"]) >= min_area
    ]
    reusable.sort(key=lambda r: r["area"], reverse=True)

    return {
        "interior_area": round(interior_area, 2),
        "used_area": round(used_area, 2),
        "waste_area": round(waste_area, 2),
        "utilization_pct": round((used_area / interior_area * 100.0), 2) if interior_area > 0 else 0.0,
        "reusable_offcuts": reusable,
    }
